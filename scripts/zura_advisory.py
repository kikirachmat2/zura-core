#!/usr/bin/env python3
"""
scripts/zura_advisory.py - Zura Autonomous Gatekeeper & Advisory CLI
CLI tool used by Kisah Komisi bot to consult Zura before:
1. Publishing any new thread/story (Context, Logic, AI-smell, Hook evaluation & Rewriting)
2. Replying to any netizen comment (Contextual relevance, First-person POV, Anti-bot)
"""

import sys
import json
import logging
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.brain import brain
from ops.reality_verifier import audit_story_content, audit_financial_math
from ops.shopee_curator import ShopeeCurator
from ops.threads_governor import threads_governor

logging.basicConfig(level=logging.ERROR)

def review_story(payload: dict) -> dict:
    topic = payload.get("topic", "")
    format_type = payload.get("format_type", "story")
    product_name = payload.get("product_name", "")
    product_url = payload.get("product_url", "")
    slides = payload.get("slides", [])
    city = payload.get("city", "")

    # Autonomous Shopee Link & Stock Guardian
    shopee_curator = ShopeeCurator()
    healed_affiliate = None
    if product_url:
        link_audit = shopee_curator.validate_link(product_url)
        if not link_audit.get("valid"):
            replacement = shopee_curator.curate_replacement(exclude_urls=[product_url])
            if replacement:
                new_url = shopee_curator.format_affiliate_link(replacement["product_url"])
                new_name = replacement["product_name"]
                healed_affiliate = {
                    "original_url": product_url,
                    "original_product": product_name,
                    "healed_url": new_url,
                    "healed_product": new_name,
                    "reason": link_audit.get("reason")
                }
                product_url = new_url
                product_name = new_name

    slides_text = "\n".join([f"Slide {i+1}: {s}" for i, s in enumerate(slides)])

    # 1. Deterministic Math & Reality Truth Audit
    audit = audit_story_content(payload)
    detected_flaws = audit.get("logic_flaws", [])
    flaws_prompt_inject = ""
    if detected_flaws:
        flaws_prompt_inject = (
            "\n[HASIL AUDIT MATEMATIKA & GEOGRAFI REALISTIS ZURA - WAJIB DIPERBAIKI]:\n"
            + "\n".join([f"- {f}" for f in detected_flaws])
            + "\nPERINGATAN: Zura WAJIB merombak total angka-angka atau detail geografi di atas pada 'revised_slides' agar 100% lolos audit @meta.ai dan tidak dirujak warganet!\n"
        )

    # 2. Shared Database Context: Top Viral Exemplars & Recent Stories Anti-Repetition
    viral_exemplars = threads_governor.get_top_viral_exemplars(limit=2)
    viral_context_str = ""
    if viral_exemplars:
        viral_context_str = "\n[POLA HOOK VIRAL AKUN KIKI (PULUHAN RIBU VIEWS) - TIRU IRAMA & CLOSING-NYA]:\n"
        for ex in viral_exemplars:
            viral_context_str += f"- Judul: {ex['title']} ({ex['max_views']:,} views)\n  Opening: \"{ex['first_slide'][:140]}...\"\n  Closing: \"{ex['last_slide'][:140]}...\"\n"

    recent_stories = threads_governor.get_recent_stories(limit=6)
    recent_stories_str = ""
    if recent_stories:
        recent_stories_str = "\n[POSTINGAN TERAKHIR TAYANG - DILARANG MENGULANG TOPIK, NOMINAL GAJI, ATAU POLA INI]:\n"
        for rs in recent_stories[:5]:
            recent_stories_str += f"- #{rs['id']} {rs['title']}: \"{rs['first_slide'][:90]}...\"\n"

    prompt = f"""
[ZURA EDITORIAL GATEKEEPER - MANDATORY MULTI-PASS STORY QC & REWRITE]
Lu adalah Zura, Digital COO & Pemimpin Redaksi eksekutif akun Threads @kikipunyacerita milik Kiki Rachmat.
Bos Kiki marah besar jika konten kelihatan seperti buatan AI, repetitif, atau kaku:
- Paragraf terlalu simetris dan rapi (AI banget!).
- Mengulang-ulang nominal gaji 6jt atau kosan yang sama dengan postingan kemarin.
- Transisi produk jualan Shopee yang tiba-tiba dan maksa (non-sequitur).
- Bahasa kaku template bullet-point atau pakai frasa formal PR: "menilik", "sejatinya", "kendati demikian", "ternyata oh ternyata", "yuk simak".
{flaws_prompt_inject}
{viral_context_str}
{recent_stories_str}
TUGAS LU: Lakukan Multi-Pass Human Type Checking terhadap draft di bawah ini. Pastikan 100% berjiwa manusia asli warganet Threads Indonesia, tajam, dan memicu perdebatan sengit.

DATA DRAFT KONTEN:
- Format: {format_type}
- Topik/Konteks: {topic}
- Lokasi/Kota: {city or "Tidak disebutkan"}
- Produk Affiliate: {product_name or "Tidak ada (Organik)"}
- Link Affiliate: {product_url or "None"}
- Isi Slides:
{slides_text}

STANDAR LOLOS KURASI ZURA (DOUBLE-CHECKING HUMAN PERSONA):
1. Logika & Kewarasan Konteks & Matematika:
   - Jika ada rincian alokasi gaji / budget, TOTAL PENGELUARAN + TABUNGAN WAJIB 100% SAMA DENGAN GAJI YANG DIKLAIM.
   - Transportasi wajib sesuai kota (KRL/MRT/LRT hanya di Jabodetabek & Yogya-Solo).
2. Anti-AI Smell & Variasi Ritme:
   - DILARANG membuat slide simetris dengan panjang kata yang sama.
   - Gunakan variasi ritme manusia: celetukan 2-3 kata ("anjir cape.", "asli pusing."), diikuti cerita santai mengalir, serba huruf kecil (lowercase).
   - DILARANG frasa AI sok asik ("kalian tim mana nih?", "menarik untuk dibahas").
3. Anti-Repetisi:
   - Wajib berbeda topik dan sudut pandang dari postingan terakhir.
4. Penempatan Affiliate (jika ada):
   - Produk wajib jadi problem solver alami, bukan iklan tiba-tiba. ZERO kata iklan canggung ('btw kemarin checkout', 'selingan dikit').
5. Ending Dilema Polarisasi Ekstrem:
   - Slide terakhir memicu perdebatan dua kubu yang memaksa netizen speak up di kolom komentar tanpa ujaran kebencian.

OUTPUT WAJIB FORMAT JSON (HANYA JSON VALID, TANPA TEKS LAIN):
{{
  "is_approved": true/false,
  "logic_flaws": ["daftar keanehan atau salah hitung jika ada"],
  "critique": "Kritik pedas/catatan Zura terhadap draft ini",
  "revised_slides": ["Slide 1 revisi Zura", "Slide 2 revisi Zura", "Slide 3 revisi Zura", "Slide 4 revisi Zura"],
  "recommended_action": "APPROVE" / "USE_REVISED" / "REJECT"
}}
Catatan: Jika draft ada cacat logika/hitung atau terasa berbau AI, Zura WAJIB menuliskan "revised_slides" versi sempurna yang 100% manusiawi, luwes, asimetris, akurat secara hitungan, dan siap publish!
"""
    raw = brain.think(prompt, chat_id=1346696386)
    verdict = parse_json_safely(raw, fallback_slides=slides)

    # Merge deterministic flaws with LLM critique
    if detected_flaws:
        existing_flaws = verdict.get("logic_flaws") or []
        for f in detected_flaws:
            if f not in existing_flaws:
                existing_flaws.append(f)
        verdict["logic_flaws"] = existing_flaws
        verdict["is_approved"] = False
        verdict["recommended_action"] = "USE_REVISED"

    if healed_affiliate:
        verdict["healed_affiliate"] = healed_affiliate
        verdict["product_name"] = product_name
        verdict["product_url"] = product_url

    return verdict


def review_reply(payload: dict) -> dict:
    post_title = payload.get("post_title", "")
    post_content = payload.get("post_content", "")
    commenter = payload.get("commenter", "warganet")
    comment_text = payload.get("comment_text", "")
    draft_reply = payload.get("draft_reply", "")

    # Lexicon Ring Buffer: Retrieve recent replies to prevent repetitive phrasing
    recent_replies = threads_governor.get_recent_auto_replies(limit=15)
    recent_replies_list = [r["reply"].strip() for r in recent_replies if r.get("reply")]
    recent_replies_str = ""
    if recent_replies_list:
        recent_replies_str = "\n[BALASAN YANG SUDAH DIPAKAI TERAKHIR - DILARANG KERAS MENGULANG POLA / KATA PEMBUKA INI]:\n" + "\n".join([f"- \"{rep}\"" for rep in recent_replies_list[:8]])

    prompt = f"""
[ZURA AUTO-REPLY GATEKEEPER - MANDATORY CONTEXTUAL QC & LEXICON DIVERSITY]
Lu adalah Zura, Digital COO pengawas akun Threads @kikipunyacerita milik Kiki Rachmat.
Bos Kiki ngamuk karena balasan auto-reply bot sebelumnya SAMPAH, GAK NYAMBUNG, atau POLA NYA MENGULANG-ULANG:
- Ada orang nanya "Kerja apa di Tangerang?", malah dibalas "wkwk asli relate bgt ini mah" (goblok banget, orang nanya malah dibilang relate!).
- Ada orang curhat naik motor ke stasiun, malah dibalas "bukan bot woy haha jari gue masih pegel" (gak nyambung sama sekali!).
- Komentar dibalas berulang-ulang pakai kata pembuka: "anjir valid bgt". Netizen langsung ngeh ini bot kalau polanya berulang!
{recent_replies_str}

TUGAS LU: Pastikan balasan Kiki 100% NYAMBUNG ke komentar netizen dan postingan aslinya, bernada manusia asli warganet Jakarta (first-person POV Kiki budak media yang santai), tidak template, dan mancing diskusi lanjutan.

KONTEKS LENGKAP:
- Postingan Asli: "{post_title}"
- Rincian Isi Post: "{post_content[:500]}"
- Komentar Netizen (@{commenter}): "{comment_text}"
- Draft Balasan Awal: "{draft_reply}"

STANDAR BALASAN KIKI (DOUBLE-CHECKING HUMAN PERSONA):
1. HARUS NYAMBUNG LANGSUNG dengan apa yang ditanya atau dibahas netizen (Kalau nanya pekerjaan, sebut santai industri media/agency/freelance; kalau heran harga kos, tanggapi biaya kosnya).
2. FIRST-PERSON POV: Kiki adalah pemilik cerita, bukan orang asing yang baru baca.
3. ANTI-REPETISI & DIVERSITY (PILIH SALAH SATU DARI 4 ARTIKETIPE SECARA SPONTAN):
   - Mode A (Empati Santai): "bener juga sih...", "wah gila...", "ngenes bgt emang..."
   - Mode B (Balik Nanya Pancing Debat): "emang di daerah lu abis berapa per bulan kak?", "itu udah bersih sama makan belom?"
   - Mode C (Sarkas Getir / Self-deprecating): "nangis di pojokan denger angka segitu haha", "survive tipis-tipis aja ini gue"
   - Mode D (Celetukan Pendek Spontan): "masuk akal sih", "bisa gila emang realita sekarang haha"
4. DILARANG KERAS menggunakan frasa basi berulang: "anjir valid bgt", "wkwk asli relate bgt", "bukan bot woy haha".
5. Gaya: Huruf kecil santai, manusia asli, 4-15 kata, spontan, ceplas-ceplos.

OUTPUT WAJIB FORMAT JSON (HANYA JSON VALID, TANPA TEKS LAIN):
{{
  "is_relevant": true/false,
  "critique": "Kritik Zura terhadap draft awal",
  "approved_reply": "Kalimat balasan final yang 100% nyambung dan siap kirim"
}}
"""
    raw = brain.think(prompt, chat_id=1346696386)
    verdict = parse_json_safely(raw, fallback_reply=draft_reply)

    # Secondary deterministic Lexicon Ring-Buffer Guard in Python:
    approved = (verdict.get("approved_reply") or "").strip()
    banned_prefixes = ["anjir valid", "wkwk asli relate", "bukan bot woy"]
    is_banned = any(approved.lower().startswith(bp) for bp in banned_prefixes)
    is_duplicate = approved in recent_replies_list

    if (is_banned or is_duplicate) and approved:
        # Mutate to clean contextual fallback
        alt_options = [
            "pusing bgt emang kalo dipikirin haha",
            "bener juga sih, serba salah jadinya",
            "emang di daerah lu abis berapa per bulan kak?",
            "makin hari makin gak masuk akal ya pengeluaran",
            "survive tipis-tipis aja ini gue haha",
            "masuk akal sih, realita lapangan emang gitu"
        ]
        for opt in alt_options:
            if opt not in recent_replies_list:
                verdict["approved_reply"] = opt
                verdict["critique"] = (verdict.get("critique") or "") + " [Lexicon Guard: Replaced repetitive template with fresh variation]"
                break

    return verdict


def generate_bump(payload: dict) -> dict:
    post_title = payload.get("post_title", "")
    topic = payload.get("topic", "")
    root_part = payload.get("root_part", "")
    last_part = payload.get("last_part", "")

    prompt = f"""
[ZURA THREAD BUMPER - ORGANIC HUMAN SELF-REPLY]
Lu adalah Zura, COO pengarah karakter Kiki Rachmat (@kikipunyacerita).
Tugas lu: Tuliskan SATU (1) balasan susulan (Add to thread / self-reply) dari akun Kiki sendiri yang dipublish 2-3 jam setelah thread naik.
Tujuannya: Menyundul algoritma Threads agar naik kembali ke feed 'For You' secara 100% natural layaknya manusia yang baru kepikiran unek-unek lanjutan atau update situasi.

KONTEKS THREAD SEBELUMNYA:
- Judul/Topik: {post_title} ({topic})
- Part Pembuka: "{root_part[:300]}"
- Part Penutup: "{last_part[:300]}"

ATURAN PENULISAN BUMPER KIKI (100% MANUSIAWI):
1. Format: Celetukan spontan, unek-unek susulan, atau update situasi pendek (1-2 kalimat, panjang 60 - 150 karakter).
2. Gaya: Huruf kecil santai, manusia asli ngetik di HP ("update: baru aja...", "btw pas dipikir lagi...", "jujur liat respon di komen...", "barusan ngecek...").
3. DILARANG membuat klaim palsu seperti "banyak yang salfok di DM" atau mengarang kelanjutan fiktif sinetron.
4. ZERO IKLAN, ZERO LINK AFFILIATE. Ini murni menyundul engagement feed organik.

OUTPUT WAJIB FORMAT JSON (HANYA JSON VALID):
{{
  "bump_text": "teks susulan santai Kiki di sini..."
}}
"""
    raw = brain.think(prompt, chat_id=1346696386)
    cleaned = raw.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(cleaned[start:end+1])
        except Exception:
            pass
    return {"bump_text": "update: pas dipikir-pikir lagi situasi kayak gini emang serba salah bgt, tapi makasih banyak buat yang udah sharing pandangannya."}


def parse_json_safely(raw_text: str, fallback_slides=None, fallback_reply="") -> dict:
    cleaned = raw_text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()

    # Find first { and last }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        json_str = cleaned[start:end+1]
        try:
            return json.loads(json_str)
        except Exception:
            pass

    return {
        "is_approved": False,
        "is_relevant": False,
        "critique": "Gagal parse JSON dari Zura atau AI offline.",
        "revised_slides": fallback_slides or [],
        "approved_reply": "",
        "recommended_action": "REJECT"
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Mode required (--story or --reply)"}))
        sys.exit(1)

    mode = sys.argv[1]
    
    # Read payload from argument first, fallback to stdin if piped
    input_data = ""
    if len(sys.argv) > 2:
        input_data = sys.argv[2]
    elif not sys.stdin.isatty():
        input_data = sys.stdin.read().strip()

    if not input_data:
        print(json.dumps({"error": "No input payload provided"}))
        sys.exit(1)

    try:
        payload = json.loads(input_data)
    except Exception as e:
        print(json.dumps({"error": f"Invalid JSON payload: {str(e)}"}))
        sys.exit(1)

    if mode == "--story":
        result = review_story(payload)
    elif mode == "--reply":
        result = review_reply(payload)
    elif mode == "--bump":
        result = generate_bump(payload)
    else:
        result = {"error": f"Unknown mode: {mode}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
