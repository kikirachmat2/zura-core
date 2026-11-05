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

logging.basicConfig(level=logging.ERROR)

def review_story(payload: dict) -> dict:
    topic = payload.get("topic", "")
    format_type = payload.get("format_type", "story")
    product_name = payload.get("product_name", "")
    product_url = payload.get("product_url", "")
    slides = payload.get("slides", [])
    city = payload.get("city", "")

    slides_text = "\n".join([f"Slide {i+1}: {s}" for i, s in enumerate(slides)])

    prompt = f"""
[ZURA EDITORIAL GATEKEEPER - MANDATORY STORY QC & REWRITE]
Lu adalah Zura, COO & Pemimpin Redaksi eksekutif akun Threads @kikipunyacerita.
Bos Kiki marah besar karena konten sebelumnya kelihatan tolol, gak mikir, dan kaku kayak bot AI:
- Masa ngekos di Surabaya dibilang naik KRL (Surabaya gak ada KRL!).
- Masa udah bayar sewa kontrakan tapi nyicil KPR barengan tanpa konteks logis.
- Masa cerita kebocoran rahasia negara diselingi sabun cuci muka tiba-tiba.
- Angka-angka kaku dipaksakan kayak template laporan kantor.

TUGAS LU: Evaluasi draft di bawah ini dengan standar tajam, logis, dan 100% manusiawi warganet Threads.

DATA DRAFT KONTEN:
- Format: {format_type}
- Topik/Konteks: {topic}
- Lokasi/Kota: {city or "Tidak disebutkan"}
- Produk Affiliate: {product_name or "Tidak ada (Organik)"}
- Link Affiliate: {product_url or "None"}
- Isi Slides:
{slides_text}

KRITERIA PENILAIAN ZURA:
1. Logika & Kewarasan Konteks: Apakah ada keanehan/plot-hole? (Transportasi gak sesuai kota, dobel biaya konyol, alur gak masuk akal).
2. Deteksi AI / Kelihatan Robot: Apakah gaya tulisannya mengalir natural seperti manusia asli curhat di Threads (lowercase santai, berantakan emosional) ATAU masih kaku kayak template bullet-point AI?
3. Penempatan Affiliate (jika ada): Apakah produk menjadi problem solver langsung dari masalah yang dibahas, atau selingan mendadak yang kaku? DILARANG ADA FRASA IKLAN CANGGUNG seperti 'selingan dikit' atau 'btw kemarin gue checkout'!
4. Ending Dilema Polarisasi Ekstrem (Polarizing Dilemma): Apakah slide terakhir memicu perdebatan sengit dua kubu? Jika masih berupa pertanyaan hambar ('kalian tim mana?', 'spill dong'), ZURA WAJIB merombaknya menjadi dilema ekstrem yang memaksa netizen memihak dan berdebat di komentar!

OUTPUT WAJIB FORMAT JSON (HANYA JSON VALID, TANPA TEKS LAIN):
{{
  "is_approved": true/false,
  "logic_flaws": ["daftar keanehan jika ada"],
  "critique": "Kritik pedas/catatan Zura terhadap draft ini",
  "revised_slides": ["Slide 1 revisi Zura", "Slide 2 revisi Zura", "Slide 3 revisi Zura", "Slide 4 revisi Zura"],
  "recommended_action": "APPROVE" / "USE_REVISED" / "REJECT"
}}
Catatan: Jika draft ada cacat logika atau masih terasa kaku AI, Zura WAJIB menuliskan "revised_slides" versi sempurna yang 100% manusiawi, luwes, masuk akal, dan siap publish!
"""
    raw = brain.think(prompt, chat_id=1346696386)
    return parse_json_safely(raw, fallback_slides=slides)


def review_reply(payload: dict) -> dict:
    post_title = payload.get("post_title", "")
    post_content = payload.get("post_content", "")
    commenter = payload.get("commenter", "warganet")
    comment_text = payload.get("comment_text", "")
    draft_reply = payload.get("draft_reply", "")

    prompt = f"""
[ZURA AUTO-REPLY GATEKEEPER - MANDATORY CONTEXTUAL QC]
Lu adalah Zura, COO pengawas akun Threads @kikipunyacerita milik Kiki Rachmat.
Bos Kiki ngamuk karena balasan auto-reply bot sebelumnya SAMPAH dan GAK NYAMBUNG:
- Ada orang nanya "Kerja apa di Tangerang?", malah dibalas "wkwk asli relate bgt ini mah" (goblok banget, orang nanya malah dibilang relate!).
- Ada orang curhat naik motor ke stasiun, malah dibalas "bukan bot woy haha jari gue masih pegel" (gak nyambung sama sekali!).
- Postingan bahas Surabaya, balasannya malah nyebut kosan Jakpus.

TUGAS LU: Pastikan balasan Kiki 100% NYAMBUNG ke komentar orang ini dan postingan aslinya, bernada manusia asli (first-person POV Kiki budak media santai), gak template, dan mancing diskusi lanjutan.

KONTEKS LENGKAP:
- Postingan Asli: "{post_title}"
- Rincian Isi Post: "{post_content[:500]}"
- Komentar Netizen (@{commenter}): "{comment_text}"
- Draft Balasan Awal: "{draft_reply}"

KRITERIA BALASAN KIKI:
1. HARUS NYAMBUNG LANGSUNG dengan apa yang ditanya atau dibahas netizen (Kalau dia nanya pekerjaan, jawab santai pekerjaan freelance/media/agency; kalau dia heran harga kos, tanggapi biaya kosnya).
2. FIRST-PERSON POV: Kiki adalah pemilik cerita, bukan orang asing yang baru baca.
3. DILARANG menggunakan template basi: "wkwk asli relate bgt", "bukan bot woy haha", "anjir valid bgt".
4. Gaya: Huruf kecil santai, manusia asli, 4-15 kata, spontan, ceplas-ceplos.

OUTPUT WAJIB FORMAT JSON (HANYA JSON VALID, TANPA TEKS LAIN):
{{
  "is_relevant": true/false,
  "critique": "Kritik Zura terhadap draft awal",
  "approved_reply": "Kalimat balasan final yang 100% nyambung dan siap kirim"
}}
"""
    raw = brain.think(prompt, chat_id=1346696386)
    return parse_json_safely(raw, fallback_reply=draft_reply)


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
