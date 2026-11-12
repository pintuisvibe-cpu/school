# স্কুল অ্যাটেনডেন্স · Face + QR

ব্রাউজারেই মুখ (face) মেলানো হয় — কোনো paid face API বা API key লাগে না। সার্ভারে শুধু
১২৮ সংখ্যার face descriptor যায়, ছবি যায় না। ডেটা থাকে **Supabase Postgres**-এ
(অথবা Supabase কনফিগার না থাকলে লোকাল SQLite ফাইলে)।

## যা যা কাজ করে

| অংশ | কাজ |
| --- | --- |
| `/admin` | শিক্ষার্থী রেজিস্ট্রেশন (ছবি আপলোড বা ওয়েবক্যাম), QR কার্ড তৈরি ও ডাউনলোড, আজকের উপস্থিতি, CSV ডাউনলোড |
| `/scanner` | গেট স্ক্যানার: QR পড়ে + লাইভ ক্যামেরায় মুখ মিলিয়ে উপস্থিতি রেকর্ড, ডুপ্লিকেট আটকায়, সফল/ব্যর্থ ওভারলে ও শব্দ |
| অ্যাডমিন প্যানেল | পুরোনো শিক্ষার্থী (যাদের face data নেই) তাঁদের ছবি দিয়ে **Face যোগ** |
| ব্যাকএন্ড | FastAPI + Supabase PostgREST, ঢাকা সময় (Asia/Dhaka), দিনে একবার উপস্থিতি |

QR কোডে Student ID নয়, বরং `card_token` (১৬ অক্ষরের random টোকেন) থাকে। ফলে কার্ড
হাতে পেয়েও কেউ সহজে Student ID অনুমান করতে পারে না। পুরোনো ID-ভিত্তিক QR-ও এখনো
কাজ করে, কারণ ব্যাকএন্ড Student ID ও card token — দুটোই খোঁজে।

## ফাইল

```
main.py                        FastAPI রুট + face যাচাইয়ের নিয়ম
storage.py                     Supabase ও SQLite — দুটো ব্যাকএন্ড, একই ইন্টারফেস
admin.html                     অ্যাডমিন ড্যাশবোর্ড (face processing ব্রাউজারে)
scanner.html                   গেট স্ক্যানার (QR + লাইভ face)
migrate_sqlite_to_supabase.py  পুরোনো attendance.db → Supabase
render.yaml, .env.example      ডিপ্লয়মেন্ট ও কনফিগ
```

## লোকাল রানে

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

তারপর খুলুন `http://localhost:8000/admin` (ওয়েবক্যামের জন্য Chrome/Safari) এবং
`http://localhost:8000/scanner`। `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` সেট না থাকলে
লোকাল `attendance.db` ব্যবহার হবে — ডেমো ও টেস্টের জন্য এটাই সহজ।

## Supabase সেটআপ

প্রজেক্টে `students`, `attendance`, `school_settings` টেবিল আগেই আছে। সার্ভারকে শুধু
দুটো environment variable দিতে হবে:

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role / secret key>
```

- key নিন Supabase Dashboard → **Project Settings → API keys** থেকে
  (`service_role`, অথবা নতুন `sb_secret_...` key)।
- এই key **শুধু সার্ভারে** থাকবে — HTML/JS-এ বা Git-এ কখনো নয়। `.env` ফাইল
  `.gitignore`-এ আছে।
- `students`/`attendance` টেবিলে RLS চালু আছে এবং কোনো policy নেই; তাই anon key দিয়ে
  কেউ পড়তে/লিখতে পারবে না। service key RLS bypass করে, অর্থাৎ ডেটা শুধু আমাদের API
  দিয়েই যাবে।
- সার্ভার নিজে থেকেই `/rest/v1` (PostgREST) ব্যবহার করে, আলাদা ড্রাইভার বা পাসওয়ার্ড
  লাগে না।

### পুরোনো ডেটা সরানো

```bash
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python migrate_sqlite_to_supabase.py attendance.db
```

স্ক্রিপ্টটি শিক্ষার্থী, face descriptor, card token (প্রিন্ট করা QR অকার্যকর হবে না)
এবং প্রতিদিনের উপস্থিতি কপি করে; দুবার চালালেও ডুপ্লিকেট হয় না।

## ডিপ্লয় (Render)

`render.yaml` আছে — Render-এ New → Blueprint দিয়ে রিপো repo সংযোগ করুন, তারপর
`SUPABASE_URL` ও `SUPABASE_SERVICE_KEY` বসান (start command:
`uvicorn main:app --host 0.0.0.0 --port $PORT`)।

- ক্যামেরার জন্য অবশ্যই **HTTPS** লিংক দরকার (Render নিজেই দেয়)।
- admin, scanner ও API একই origin-এ থাকলে `API_BASE_URL = ""` ঠিক আছে। ফ্রন্টএন্ড
  আলাদা হোস্টে (যেমন Netlify) হলে `admin.html`/`scanner.html`-এর
  `API_BASE_URL`-এ Render URL দিন এবং `CORS_ORIGINS`-এ সেই ডোমেইন রাখুন।

## API

| মেথড | রুট | কাজ |
| --- | --- | --- |
| GET | `/health` | সার্ভার ও storage (`supabase`/`sqlite`) স্ট্যাটাস |
| POST | `/api/register` | `{student_id, name, class_name, face_descriptor}` → `card_token` |
| POST | `/api/enroll-face` | পুরোনো শিক্ষার্থীর face descriptor যোগ |
| POST | `/api/verify-attendance` | `{student_id (বা card token), face_descriptor}` → উপস্থিতি |
| GET | `/api/attendance?day=YYYY-MM-DD` | ঐ দিনের রিপোর্ট (ডিফল্ট আজ) |
| GET | `/api/students` | শিক্ষার্থী তালিকা, face আছে কি না |

`API_ACCESS_TOKEN` সেট করলে সব `/api/*` রুটে `Authorization: Bearer <token>` লাগবে।

## নিরাপত্তা ও সম্মতি

- face descriptor বায়োমেট্রিক ডেটা; অভিভাবকের অবহিত সম্মতি ছাড়া নিবন্ধন করবেন না।
- ছবি সার্ভারে যায়/জমা হয় না — শুধু descriptor।
- `service_role` key ফাঁস হলে ডেটাবেস পুরো খোলা; ফাঁস হলে Supabase থেকে key বদলান।
- বাস্তবে চালানোর আগে `API_ACCESS_TOKEN` সেট করা এবং `CORS_ORIGINS` নির্দিষ্ট ডোমেইনে
  সীমিত করা ভালো।

## সীমাবদ্ধতা

- face model প্রথমবার CDN (jsDelivr) থেকে ডাউনলোড হয় — ইন্টারনেট দরকার; না হলে
  মডেল লোডের এরর দেখাবে, ছবি তুললে কাজ করবে না।
- ফ্রেমে ঠিক একজন থাকতে হবে; একাধিক মুখ থাকলে স্ক্যান বাতিল হয়।
- লাইভনেস (ছবি/ভিডিও দিয়ে ফাঁকি) শনাক্তকরণ নেই; গুরুত্বপূর্ণ হলে গেটে শিক্ষক/স্টাফ
  রাখুন।
- দিনে একবারই উপস্থিতি; দ্বিতীয়বার স্ক্যানে "আজকের উপস্থিতি ইতিমধ্যে রেকর্ড করা
  হয়েছে" দেখাবে।
- `/api/attendance` এক দিনের ডেটা দেয়; মাসিক রিপোর্ট এখনো নেই।
