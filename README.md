# School ID Card & Gate Attendance

আসল স্ক্যানযোগ্য QR সহ আইডি কার্ড, ব্রাউজারেই ওয়েবক্যাম ফেস এনরোলমেন্ট, আর গেটে QR + ফেস মিলিয়ে উপস্থিতি — সব ডেটা আপনার নিজের **Supabase** প্রজেক্টে।

- ব্যাকএন্ড: Supabase Postgres (project `nojpjuowrhinkxpzumum`, region `ap-southeast-1`)
- ফ্রন্টএন্ড: প্লেইন HTML/CSS/JS (কোনো বিল্ড স্টেপ নেই), FastAPI শুধু ফাইল সার্ভ করে
- ফেস: [@vladmandic/face-api](https://github.com/vladmandic/face-api) — মডেল ও লাইব্রেরি রিপোতে ভেন্ডর করা, ছবি কোথাও আপলোড হয় না
- QR: `qrcode-generator` দিয়ে লোকালি তৈরি, ডিকোড `jsQR` দিয়ে

## পেজ

| রুট | কাজ |
| --- | --- |
| `/` | হোম — লাইভ কাউন্ট, আজকের উপস্থিতি |
| `/admin` | অ্যাডমিন কনসোল — PIN গেট, শিক্ষার্থী CRUD, ফেস এনরোলমেন্ট, উপস্থিতি রিপোর্ট, CSV, স্কুল সেটিংস |
| `/cards` | আইডি কার্ড স্টুডিও — সব কার্ড, PNG/প্রিন্ট (A4-এ ২টি করে) |
| `/card?t=…` | QR স্ক্যান করলে যে যাচাই পেজ খোলে |
| `/scanner` | গেট স্ক্যানার — ক্যামেরা QR + লাইভ ফেস ম্যাচ |

## ডিফল্ট অ্যাডমিন PIN

```
123456
```

প্রথমেই **অ্যাডমিন → স্কুল ও সেটিংস → PIN পরিবর্তন** থেকে বদলে নিন।

## ডেটাবেস (Supabase)

তিনটি টেবিল, তিনটিতেই RLS চালু এবং **কোনো policy নেই** — তাই anon key দিয়ে সরাসরি টেবিল পড়া/লেখা অসম্ভব। সব অ্যাক্সেস `security definer` RPC দিয়ে:

`public_settings`, `public_stats`, `public_student_by_token`,
`gate_attendance`, `admin_login`, `admin_list_students`, `admin_save_student`,
`admin_set_face`, `admin_set_photo`, `admin_set_token`, `admin_delete_student`,
`admin_attendance`, `admin_mark`, `admin_unmark`, `admin_get_settings`,
`admin_save_settings`, `admin_reset_students`

- অ্যাডমিন ফাংশনগুলো PIN যাচাই করে; PIN ডেটাবেসে SHA-256 হ্যাশ হিসেবে থাকে
- `gate_attendance` টোকেন + face descriptor নেয়, দূরত্ব ≤ 0.50 হলে আজকের উপস্থিতি লেখে (একবারই)
- QR-এ স্টুডেন্ট আইডি নয়, প্রতিটি শিক্ষার্থীর **ইউনিক কার্ড টোকেন** থাকে — নতুন টোকেন দিলে পুরোনো কার্ড বাতিল

## চালানো

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

`http://localhost:8000` খুলুন। ক্যামেরা ও QR স্ক্যানারের জন্য **HTTPS বা localhost** দরকার।

Render/Netlify/Vercel-এ ডিপ্লয় করলে:
1. অ্যাডমিন → সেটিংসে **অ্যাপের URL** বসান (যেমন `https://your-school.onrender.com`) — QR এই লিংকেই যাবে
2. স্ট্যাটিক হোস্ট ব্যবহার করলে পুরো রিপো রুট ডিপ্লয় করুন (paths `/static/...`, `/css/...`, `/js/...`)

## স্কুল সেটআপ

1. `/admin` → PIN → **স্কুল ও সেটিংস**: নাম, EIIN, ঠিকানা, লোগো, শিক্ষাবর্ষ, কার্ডের মেয়াদ, কার্ডের রং
2. **শিক্ষার্থী** ট্যাব → নতুন শিক্ষার্থী: Student ID, নাম, শ্রেণি, ছবি (আপলোড বা ওয়েবক্যাম), সম্মতির টিক → সংরক্ষণ
3. `/cards` → কার্ড প্রিভিউ, PNG বা প্রিন্ট
4. `/scanner` ফোন/ট্যাবে খুলে গেটে রাখুন — ফেস এনরোল করা থাকলে QR + ফেস, না থাকলে শুধু QR

## ডেমো ডেটা

`STU-1001 … STU-1005` — ৫ জন শিক্ষার্থী, ছবি ও কার্ড টোকেন সহ; আজকের ২টি উপস্থিতি। `admin_reset_students` (সেটিংস → ডেমো ডেটা মুছুন) দিয়ে সব মুছে নিজের ডেটা শুরু করুন।

## গোপনীয়তা

মুখের ১২৮-সংখ্যার descriptor বায়োমেট্রিক তথ্য। অভিভাবকের সম্মতি ছাড়া এনরোলমেন্ট নয়, এবং ব্যবহারকারীর মূল ছবি সার্ভারে যায় না — শুধু কার্ডে ছাপার জন্য ছোট পোর্ট্রেট সংরক্ষিত হয়।
