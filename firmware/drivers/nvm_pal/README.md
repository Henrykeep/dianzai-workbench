# nvm_pal — 板上掉电存储 → persist

`nvm_pal_layout(&kv, &bb, bb_units)`：前 `bb_units` 个擦除单位给黑匣子冻结区，其余给参数键值区（至少 2 个单位）。板子没有存储区返回 DZ_ENOTSUP。见 firmware/framework/persist/README.md。
