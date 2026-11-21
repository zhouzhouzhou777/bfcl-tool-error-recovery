# Vendored BFCL source

Source: [ShishirPatil/gorilla at revision `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`](https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8), licensed under Apache 2.0. The original license is provided as `LICENSE.bfcl`.

Files are copied without content changes. The JSON answer and tool-document files were renamed locally to distinguish them from the questions and simulator.

| Local file | Upstream path under `berkeley-function-call-leaderboard/bfcl_eval` | SHA-256 |
| --- | --- | --- |
| `BFCL_v4_multi_turn_base.json` | `data/BFCL_v4_multi_turn_base.json` | `1a21a995d06fd6f20ba55de7bced30ef953ec35e998f502ec2ecf4d66ef1c43a` |
| `BFCL_v4_multi_turn_base_answers.json` | `data/possible_answer/BFCL_v4_multi_turn_base.json` | `1fee67823b317571649177dd89d63969feaae4e810cc7448ee55ba797fb7c8fc` |
| `gorilla_file_system_tools.json` | `data/multi_turn_func_doc/gorilla_file_system.json` | `c4c1b741c71e2a17c97a5dc9c4a91d89978c4eaece56494d14272d5df6c650e9` |
| `bfcl_eval/eval_checker/multi_turn_eval/func_source_code/gorilla_file_system.py` | `eval_checker/multi_turn_eval/func_source_code/gorilla_file_system.py` | `84173750930b09aaa31b90547c9bd79ce75714682608b35e78a9c1ea259faf2b` |
| `bfcl_eval/eval_checker/multi_turn_eval/func_source_code/long_context.py` | `eval_checker/multi_turn_eval/func_source_code/long_context.py` | `5c9a5710115609c779e5b2ccb43f6ad58271ed96f2ea7a797edb0d65c385aa38` |

`long_context.py` is an import dependency of the simulator. This experiment uses ordinary filesystem scenarios. Only `prepare_cases.py` generates the adapted experimental checkpoints, injected calls, and paired error messages.
