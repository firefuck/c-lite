# Spesifikasi

Satu dokumen per modul: apa tanggung jawabnya, perilaku apa yang dijamin tes, apa yang sudah
ada, dan apa yang belum. Dokumen ini adalah titik awal sebelum mengubah sebuah modul.

## Legenda status

| Tanda | Arti |
|---|---|
| ✅ | Ada dan diuji oleh suite |
| 🟡 | Ada sebagian, atau ada tetapi belum diverifikasi di lingkungan nyata. Kolom catatan menyebut yang kurang |
| ⬜ | Belum ada. Kolom catatan menyebut task roadmap-nya bila sudah dijadwalkan |
| ⬜ belum diverifikasi | Kodenya ada, tetapi belum pernah dijalankan terhadap hal yang sebenarnya |

"Diuji" berarti ada tes di suite yang gagal bila perilaku itu rusak. Daftar apa yang belum
pernah dijalankan di lingkungan nyata ada di [STATUS.md](../STATUS.md).

## Daftar

| Modul | Lapisan | Dokumen |
|---|---:|---|
| `core` | 0 | [core.md](core.md) |
| `state` | 1 | [state.md](state.md) |
| `providers` | 1 | [providers.md](providers.md) |
| `plugins` | 1 dan 5 | [plugins.md](plugins.md) |
| `skills` | 2 | [skills.md](skills.md) |
| `tools` | 3 | [tools.md](tools.md) |
| `agent` | 4 | [agent.md](agent.md) |
| `cron` | 6 | [cron.md](cron.md) |
| `runtime` | 7 | [runtime.md](runtime.md) |
| `rpc` | 8 | [rpc.md](rpc.md) |
| `gateway` | 8 | [gateway.md](gateway.md) |
| `server` (dan dashboard) | 9 | [server.md](server.md) |
| `cli` | 10 | [cli.md](cli.md) |
| TUI dan klien bersama (TypeScript) | - | [tui.md](tui.md) |
| Desktop (Electron) | - | [desktop.md](desktop.md) |

Halaman yang dihasilkan dari kode (selalu akurat, jangan disunting):
[peta modul](../referensi/peta-modul.md) dan [katalog](../referensi/katalog.md).

## Aturan memelihara spesifikasi

- Perubahan perilaku yang dijanjikan di bagian "Kontrak" mengubah dokumen ini dalam commit
  yang sama.
- Fitur baru mengubah baris di tabel status dari ⬜ ke ✅ hanya bila ada tesnya.
- Sesuatu yang ditulis tetapi belum pernah dijalankan diberi 🟡 atau "belum diverifikasi",
  bukan ✅.
