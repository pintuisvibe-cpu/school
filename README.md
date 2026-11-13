# স্কুল অ্যাটেনডেন্স · Face + QR

ব্রাউজারেই ছবি থেকে মুখের ১২৮ সংখ্যার descriptor তৈরি হয়; সার্ভার সেই descriptor
সংরক্ষণ ও তুলনা করে — কোনো paid face API লাগে না। মূল ছবি সার্ভারে যায় না।
ডেটা থাকে **Supabase Postgres**-এ (অথবা Supabase কনফিগার না থাকলে লোকাল SQLite ফাইলে)।

## যা যা কাজ করে

| অংশ | কাজ |
| --- | --- |
| `/admin` | শিক্ষার্থী রেজিস্ট্রেশন (ছবি আপলোড বা ওয়েবক্যাম), QR কার্ড তৈরি ও ডাউনলোড, আজকের উপস্থিতি, CSV ডাউনলোড |
| `/scanner` | গেট স্ক্যানার: QR পড়ে + লাইভ ক্যামেরায় মুখ মিলিয়ে উপস্থিতি রেকর্ড, ডুপ্লিকেট আটকায়, সফল/ব্যর্থ ওভারলে ও শব্দ |
| অ্যাডমিন প্যানেল | পুরোনো শিক্ষার্থী (যাদের face data নেই) তাঁদের ছবি দিয়ে **Face যোগ** |
| ব্যাকএন্ড | FastAPI + Supabase PostgREST, ঢাকা সময় (Asia/Dhaka), দিনে একবার উপস্থিতি |

নতুন QR কোডে Student ID নয়, `card_token` (১৮ অক্ষরের, ৯ বাইট random টোকেন) থাকে।
পুরোনো ID-ভিত্তিক QR-ও কাজ করে, কারণ ব্যাকএন্ড Student ID ও card token — দুটোই খোঁজে।
কার্ডটি অনুলিপি করা সম্ভব; উপস্থিতি দেওয়ার আগে লাইভ face descriptor-ও মেলানো হয়।

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
লোকাল `attendance.db` ব্যবহার হবে — ডেমো ও টেস্টের জন্য এটাই সহজ। `.env.example`
শুধু নমুনা; প্রয়োজন হলে OS environment-এ আসল মান `export` করুন, অথবা মানগুলো
`.env`-এ লিখে `uvicorn main:app --env-file .env --reload --port 8000` চালান।

## Supabase সেটআপ

প্রজেক্টে `students`, `attendance`, `school_settings` টেবিল আগেই আছে। সার্ভারকে শুধু
দুটো environment variable দিতে হবে:

```bash
SUPABASE_URL=https://nojpjuowrhinkxpzumum.supabase.co
SUPABASE_SERVICE_KEY=<service_role / secret key>
```

- key নিন Supabase Dashboard → **Project Settings → API keys** থেকে
  (নতুন `sb_secret_...` বা পুরোনো `service_role` JWT)। অ্যাপ নিজেই নতুন key
  `apikey` header-এ এবং পুরোনো JWT প্রয়োজনে Bearer header-এ পাঠায়।
- এই key **শুধু সার্ভারে** থাকবে — HTML/JS-এ বা Git-এ কখনো নয়। `.env` ফাইল
  `.gitignore`-এ আছে। `SUPABASE_URL` বা key একটিমাত্র সেট থাকলে অ্যাপ শুরু হবে না;
  ভুল করে অস্থায়ী SQLite-এ তথ্য লেখার বদলে সঠিক কনফিগারেশন দিতে হবে।
- `students`/`attendance` টেবিলে RLS চালু আছে এবং কোনো policy নেই; তাই anon key দিয়ে
  কেউ পড়তে/লিখতে পারবে না। service key RLS bypass করে, অর্থাৎ ডেটা শুধু আমাদের API
  দিয়েই যাবে।
- সার্ভার নিজে থেকেই `/rest/v1` (PostgREST) ব্যবহার করে, আলাদা ড্রাইভার বা পাসওয়ার্ড
  লাগে না।

### পুরোনো ডেটা সরানো

```bash
SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python migrate_sqlite_to_supabase.py attendance.db
```

স্ক্রিপ্টটি শিক্ষার্থী, face descriptor, card token, section/roll/active/expiry/session
(যে কলামগুলো SQLite-এ আছে), উপস্থিতির status/method কপি করে; দুবার চালালেও
ডুপ্লিকেট হয় না। **Face data না থাকলেও শিক্ষার্থী কপি হয়** — তারপর `/admin` থেকে
"Face যোগ" করতে পারবেন। পুরোনো QR-এর token থাকলে সেটিই রাখা হয়; SQLite-এ token
না থাকলে নতুনটি তৈরি হয় (পুরোনো ID-ভিত্তিক QR-ও কাজ করে)। কোনো রেকর্ড কপি করতে
ব্যর্থ হলে স্ক্রিপ্ট তা জানিয়ে non-zero exit code দেয়। একই Student ID-তে
Supabase ও SQLite-র card token ভিন্ন হলে কোন QR বৈধ থাকবে তা না বদলে ত্রুটি দেখায়;
কার্ডগুলো মিলিয়ে হাতে ঠিক করুন।

## ডিপ্লয় (Render)

`render.yaml` আছে — Render-এ New → Blueprint দিয়ে এই রিপো সংযোগ করলে
`SUPABASE_URL` (public project URL) Blueprint থেকে বসবে। `SUPABASE_SERVICE_KEY`
**Render Dashboard → Web Service → Environment**-এ নিজে দিতে হবে; GitHub-এ,
HTML-এ বা chat-এ service key দেবেন না। `API_ACCESS_TOKEN` Blueprint sync হলে
Render একটি ২৫৬-bit random মান তৈরি করে (আগের মান থাকলে বদলায় না)। ওই মান Render
Environment-এ দেখে admin/scanner-এর **API টোকেন** বোতামে দিন; এটি Supabase key নয়।
`CORS_ORIGINS`-এ নিজের site-এর HTTPS origin দিন (যেমন `https://<আপনার-সাইট>.onrender.com`)।
start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`।

**আগে তৈরি Render service হলে:** শুধু GitHub-এ `render.yaml` push করলে নতুন
`sync: false` secret বসে যায় না; Blueprint-ও sync করতে হয়, আর সরাসরি GitHub-
connected service হলে Blueprint-এর env settings স্বয়ংক্রিয়ভাবে প্রযোজ্য নাও হতে
পারে। সেই ক্ষেত্রে Render Environment-এ নিজে `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, একটি দীর্ঘ random `API_ACCESS_TOKEN` এবং `CORS_ORIGINS`
যোগ/যাচাই করুন; Save, deploy করুন। Render-এর সাথে সংযোগ ছাড়া কেউ service key বা
ওখানকার environment variables বসাতে/যাচাই করতে পারবে না।

- ক্যামেরার জন্য অবশ্যই **HTTPS** লিংক দরকার (Render নিজেই দেয়)।
- Render-এ Supabase URL/key ও API token অনুপস্থিত থাকলে অ্যাপ **চালু হবে না**;
  অস্থায়ী SQLite-এ তথ্য লেখা বা অনুমতি ছাড়া বায়োমেট্রিক API খোলা রাখার চেয়ে
  নিরাপদে ব্যর্থ হওয়া ভালো। লোকালে Supabase ছাড়া SQLite চলবে।
- deploy-এর পরে `/health`-এ `storage: supabase` এবং `auth_required: true` দেখুন;
  তারপরে `GET /api/students` সঠিক Bearer token দিলে 200, না দিলে 401 কিনা দেখুন।
  `/health` ডেটাবেসে লাইভ সংযোগ পরীক্ষা করে না—সেই API কলটি গুরুত্বপূর্ণ।
- Render সাধারণত configured deploy branch (`main` হলে `main`) অনুসরণ করে। শুধু
  অন্য branch-এ push দিলে production deploy হবে না; PR merge/branch সেটিং দেখুন।
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
`/admin` ও `/scanner`-এর **API টোকেন** বোতামে **এই টোকেনটি** লিখে "সেট করুন" চাপুন
(Supabase service key **নয়**)। টোকেনটি ওই browser tab-এর `sessionStorage`-এ থাকে;
রিলোডে থাকে, ট্যাব বন্ধ করলে বা "মুছুন" চাপলে চলে যায়। দুই পেজ আলাদা ট্যাবে হলে
দুইটিতেই দিতে হবে। URL-এর `?token=`-এ দেবেন না: ইতিহাস/লগে ফাঁস হতে পারে।
`/health`-এ `storage` ও `auth_required` দেখা যায়; এটি কোন backend বাছাই হয়েছে
জানায়, **ডেটাবেসে সংযোগ পরীক্ষা করে না**। সংযোগ/অনুমতির ভুলে API 503 দেবে।

## পরীক্ষা

```bash
pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

SQLite ও mocked Supabase REST-এ নিবন্ধন, face যাচাই, অনুপস্থিত face যোগ, ডুপ্লিকেট,
মেয়াদ, রিপোর্ট, ৫০০+ রেকর্ডের পেজিং, migration ও ভুল ইনপুটের পরীক্ষা চলে। Node.js
থাকলে admin/scanner-এর browser-logic smoke test-ও চলে। আসল ক্যামেরা ও CDN মডেল
লোড অবশ্যই browser-এ HTTPS দিয়ে আলাদা করে পরীক্ষা করুন।

## নিরাপত্তা ও সম্মতি

- face descriptor বায়োমেট্রিক ডেটা; অভিভাবকের অবহিত সম্মতি ছাড়া নিবন্ধন করবেন না।
- ছবি সার্ভারে যায়/জমা হয় না — শুধু descriptor।
- `service_role` key ফাঁস হলে ডেটাবেস পুরো খোলা; ফাঁস হলে Supabase থেকে key বদলান।
- বাস্তবে চালানোর আগে আলাদা, দীর্ঘ random `API_ACCESS_TOKEN` সেট করুন এবং
  `CORS_ORIGINS` নির্দিষ্ট ডোমেইনে সীমিত করুন। এই **একটি শেয়ার করা টোকেন** admin ও
  scanner দুটোকে সব API অধিকার দেয়; এটি কর্মীদের আলাদা role/login-এর বিকল্প নয়।
  বিশ্বস্ত ডিভাইসেই টোকেন দিন, অন্য কাউকে দেবেন না। ডিফল্টে (টোকেন না দিলে) সব API
  অননুমোদিত প্রবেশের জন্য খোলা থাকে।
- `/api/students`-এ কার্ড টোকেনও ফেরত আসে; অনুমতি ছাড়া এই তালিকা প্রকাশ করবেন না।
- Supabase-এ card-এর `valid_until` ডাটাবেস default অনুযায়ী বসে; SQLite-এ
  নতুন কার্ডে default expiry নেই। মেয়াদ/active মান বদলালে যাচাইয়ের সময় কার্যকর হয়।

## সীমাবদ্ধতা

- face model প্রথমবার CDN (jsDelivr) থেকে ডাউনলোড হয় — ইন্টারনেট দরকার; না হলে
  মডেল লোডের এরর দেখাবে, ছবি তুললে কাজ করবে না।
- ফ্রেমে ঠিক একজন থাকতে হবে; একাধিক মুখ থাকলে স্ক্যান বাতিল হয়।
- লাইভনেস (ছবি/ভিডিও দিয়ে ফাঁকি) শনাক্তকরণ নেই; গুরুত্বপূর্ণ হলে গেটে শিক্ষক/স্টাফ
  রাখুন।
- দিনে একবারই উপস্থিতি; দ্বিতীয়বার স্ক্যানে "আজকের উপস্থিতি ইতিমধ্যে রেকর্ড করা
  হয়েছে" দেখাবে।
- `/api/attendance` এক দিনের ডেটা দেয়; মাসিক রিপোর্ট এখনো নেই।
