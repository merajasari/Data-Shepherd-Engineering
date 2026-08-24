# Data Shepherd video naming

Marketing and portfolio videos use the `IntroVideo<N>` namespace.

- `IntroVideo12` is the retroactively corrected name for the historical V12 showcase.
- `IntroVideo13` is the current production.
- ML identifiers such as V8 and V10 are reserved for model generations.
- Research identifiers such as Cycle 2 and Cycle 3 are reserved for model research cycles.

Legacy `generate_datashepherd_video_v12.py` and `make_datashepherd_video_v12.sh`
remain available as compatibility entry points. New video work must not introduce
filenames or output labels such as `video_v13` or `showcase_v13`.

Canonical IntroVideo13 commands:

```bash
bash scripts/make_datashepherd_intro_video_13.sh
open outputs/data_shepherd_intro_video_13_16x9.mp4
```
