# Xk_Minecraft
An open source software-codec Data Pack Module with Instruction efficiency enhanced.

## PLT R_002 release (2026-11-19)

Minecraft Java 26.3 wool-plot codec: BMP/PNG → 16-color wool quantization → quadtree clustering → RDO planning → ordered `SETB` / `FILL` commands, executed as a vanilla data-pack function (`/reload` + `/function plot_interface:run`).

- `PLT_R_002_2026-11-19.rar` — release archive (RAR 5, solid), SHA-256 `b1009b6fe02d0f8b6ffddae9616e1b58dd23f8d804dcea28e7493d773edb940d`
- `PLT_R_002_2026-11-19/` — the same release, extracted for browsing

Package contents:

| Path | Description |
|---|---|
| `PLT/` | encoder source (READ_SOURCE / D / DIV / R / RDO / TOP) |
| `bridge/plot_batch.py` | data-pack bridge (copy of `PLOT_INTERFACE/plot_batch.py`) |
| `examples/002.png` | sample input (168×177) |
| `examples/expected/` | sample outputs (`commands.txt`, `summary.json`, `image.plt.json`) |
| `README.md`, `USAGE.md` | quick start and full usage guide |
| `DESIGN_TIMELINE.md` | code formation rationale and timeline |
| `MANIFEST.sha256` | SHA-256 of every packaged file |

Quick start:

```powershell
python -m pip install -r requirements.txt
python -m PLT.TOP.plt_top .\config.example.json
```

Then, in Minecraft Java 26.3 single-player:

```powershell
python .\bridge\plot_batch.py .\out\commands.txt --world-dir "<save folder>" --dry-run
python .\bridge\plot_batch.py .\out\commands.txt --world-dir "<save folder>"
```

```text
/reload
/function plot_interface:run
```

See `PLT_R_002_2026-11-19/USAGE.md` for configuration, output formats, bridge limits (chunk loading, 32,768 blocks per `FILL`, 65,536 commands per function) and troubleshooting.

Verify the archive:

```powershell
Get-FileHash -Algorithm SHA256 .\PLT_R_002_2026-11-19.rar
```
