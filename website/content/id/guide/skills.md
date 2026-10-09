# Skill

Skill adalah prosedur yang tersimpan: satu berkas `SKILL.md` berisi cara mengerjakan sesuatu
menurut Anda, yang dibaca model hanya ketika relevan. Bukan kode yang dijalankan — skill tidak
pernah dieksekusi — melainkan instruksi yang masuk ke percakapan saat dipakai.

Bedanya dengan menulis instruksi di pesan: skill bertahan antar-sesi, punya nama, dan muncul di
daftar yang dilihat model sebelum ia mulai bekerja. Karena itu agent bisa mengingat "begini cara
kami menulis laporan mingguan" tanpa Anda mengulanginya setiap kali.

## Melihat yang tersedia

```console
$ clite skills list
skill-authoring                bundled   meta                   Write or improve a skill (SKILL.md). Use when saving a reusable proced
meeting-action-items           bundled   productivity           Turn meeting notes or a transcript into cited decisions, owners and fo
plan-before-acting             bundled   productivity           Break a large or ambiguous task into verifiable steps before starting.
weekly-review-planning         bundled   productivity           Run a bounded weekly review over the user's notes and tasks, then prop
arxiv                          bundled   research               Search arXiv and Semantic Scholar for papers by keyword, author, categ
...
```

Kolom kedua adalah tingkat asalnya: `bundled` (dibawa paket), `local` (milik Anda di dalam home),
`project` (dari proyek tempat Anda bekerja), atau `external`.

Tujuh belas skill bawaan dikelompokkan dalam lima kategori: `meta`, `productivity`, `research`,
`software-development`, dan `web`. Isinya hal-hal seperti menulis skill baru, memecah tugas besar
sebelum mulai, mengutip sumber, dan prosedur pengembangan perangkat lunak. Daftar lengkapnya ada
di [Rujukan tool](../reference/tools.md).

Di dalam REPL, `/skills` menampilkan hal yang sama.

## Memakai skill

Model memakainya sendiri lewat tool `skills_list` dan `skill_view`: ia membaca daftar nama dan
deskripsi (itu saja yang masuk ke prompt), lalu membuka isi lengkap satu skill ketika pekerjaannya
cocok dengan deskripsi itu. Anda tidak perlu menunjuk skill; kalau agent melewatkan salah satu
yang Anda maksud, menyebut namanya sudah cukup.

Skill juga bisa dipanggil langsung sebagai perintah slash:

```console
> /grounded-citations tulis ringkasan dua halaman dari catatan riset ini
```

Isinya dikirim sebagai pesan Anda, bukan disisipkan ke system prompt. Jadi yang terjadi sama
dengan Anda menempelkan prosedur itu sendiri, dan hasilnya ikut aturan percakapan biasa.

## Menulis skill sendiri

Minta saja kepada agent, atau tulis berkasnya langsung di `~/.clite/skills/<nama>/SKILL.md`.
Formatnya mengikuti konvensi agentskills.io, sehingga skill yang ditulis untuk agent lain bisa
dipakai tanpa diubah:

```markdown
---
name: laporan-mingguan
description: Susun laporan mingguan dari catatan dan tugas. Pakai ketika diminta merekap minggu ini.
version: 1.0.0
metadata:
  clite:
    category: productivity
---

# Laporan mingguan

## Langkah
1. Baca `catatan/` dan ambil yang bertanggal minggu ini.
...
```

Nama di `name` harus sama dengan nama direktorinya. `description` adalah satu-satunya bagian yang
selalu dilihat model — tuliskan kapan skill itu dipakai, bukan hanya apa isinya. Berkas pendukung
(gambar, templat, skrip) boleh diletakkan di `references/`, `templates/`, `scripts/`, atau
`assets/` di dalam direktori skill.

Agent menulis skill lewat tool `skill_manage`, jadi Anda bisa memintanya menyimpan prosedur yang
baru saja berhasil: *"simpan cara ini jadi skill"*.

Di mana pun skill itu ditulis, salinan yang bisa disunting adalah tingkat `local` di dalam home
Anda. Menyunting skill dari tingkat lain menyalinnya ke sana lebih dulu, jadi pembaruan paket
tidak menimpa suntingan Anda.

## Memasang skill dari luar

```console
$ clite skills search arxiv
$ clite skills info arxiv
$ clite skills install arxiv
$ clite skills update arxiv
```

Sumbernya katalog (satu berkas indeks JSON) atau sebuah tap yang Anda daftarkan sendiri dengan
`clite skills tap add owner/repo`, lalu `install <nama>` mengambil entri katalog itu.

Yang diunduh **tidak pernah dijalankan** saat dipasang. Setiap berkas diperiksa dulu, dan
hasilnya ditampilkan untuk Anda setujui sebelum apa pun ditulis: teks dipindai, berkas biner
ditolak, dan skrip dilaporkan per perintah yang dikandungnya (`subprocess`, `os.system`, URL yang
dituju). Yang ditolak hanya bisa lewat `--force`. Versi baru yang ditandai pemindai juga tidak
pernah ditulis oleh `clite skills update`.

Memasang tidak menimpa suntingan Anda: kalau direktori skill itu berbeda dari yang dicatat,
`update` menampilkannya lebih dulu dan menunggu konfirmasi.

## Merapikan

Agent menumpuk skill dari waktu ke waktu. Kurator mengarsipkan yang sudah lama tidak dipakai —
dipindahkan ke `skills/.archive/`, tidak pernah dihapus — dan hanya menyentuh skill yang dibuat
agent sendiri; skill bawaan dan skill yang Anda tulis atau pasang tidak pernah menjadi kandidat.

```console
$ clite skills curate            # laporan saja, belum mengubah apa pun
$ clite skills curate --apply    # arsipkan
```

Kurator juga berjalan sendiri paling banyak sekali per `curator.interval_hours` (bawaan 168 jam)
selama pemeliharaan awal sesi, kalau `curator.enabled`. Kegagalannya tidak pernah menghalangi
sesi Anda.

## Tingkat penemuan

Nama yang sama bisa ada di beberapa tempat. Yang pertama menang, berurutan: proyek
(`.clite/skills` di dalam repositori tempat Anda bekerja), lokal (home Anda), eksternal
(`skills.external_dirs` dan direktori dari plugin), lalu bawaan.

Skill dari tingkat proyek dan eksternal berasal dari berkas orang lain — repositori hasil clone —
dan isinya diikuti sebagai prosedur. Karena itu keduanya dipindai setiap kali ditemukan, dan yang
kena dilewati tanpa dipakai. Ini alasan yang sama mengapa `CLITE_ENABLE_PROJECT_PLUGINS=1`
diperlukan untuk plugin proyek: direktori proyek bukan milik Anda sampai Anda menyatakannya.
