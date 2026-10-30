# KytyPS5 local 2-player patch (UFC 6)

Adds local 2-player support (two controllers) to a specific Windows build of the KytyPS5
emulator, so local versus works in EA SPORTS UFC 6 (PPSA23566). It is a binary patch: the
emulator's source for this build is not available. Tested in UFC 6 local versus with two
controllers.

No game files are included or modified.

## What it does

- **User service**: a second user (configured `user_id` + 1, i.e. 1001 by default) is logged
  in. The login list, login events, user name ("Player 2") and user number all report it.
- **Pad**: a second controller object is created next to the original one.
  - The first gamepad stays player 1; the DualSense features work there as before.
  - The next gamepad that connects becomes player 2.
  - `scePadOpen` / `GetHandle` for user 1001 return handle 2, and reading handle 2 returns
    controller 2.
  - Vibration, light bar, adaptive triggers and motion work for player 2. Player 2's rumble uses
    SDL's per-controller rumble, because the "DualSense features" HID path drives only one
    controller.
- The keyboard always drives player 1.

## Requirements

The patch only fits this exact emulator build. The patcher checks the original bytes at every
site and refuses to run on anything else:

| file | sha256 |
|---|---|
| original `kyty_emulator.exe` (KytyPS5 0.3.0, git `ufc-meta-clear-htile-only-20261026-16-g3309ab23f`) | `f4025d58c7ca4a129ba1de9f95b9f950abbf92316af9c67b0a57ad3ec6ed9d6b` |
| patched `kyty_emulator_2p.exe` (v3) | `356f47fee38664bd4250e96fd8fdf6e42f5f8fe8b7602eec0c8fd2de9409d2b9` |

## Use

Either download `kyty_emulator_2p.exe` from the Releases page, or build it yourself from your own
copy of the original:

```
pip install keystone-engine capstone
python kyty_2p_patcher.py kyty_emulator.exe kyty_emulator_2p.exe kyty_2p_listing.txt
```

The launcher always starts `kyty_emulator.exe`, so keep a backup of the original and swap the
files:

```
Rename-Item kyty_emulator.exe kyty_emulator_orig.exe
Copy-Item kyty_emulator_2p.exe kyty_emulator.exe
```

Connect player 1's controller first, then player 2's, and start the game from the launcher.

## Files

- `kyty_2p_patcher.py`: builds the patched exe from the original. It adds a new code section and
  checks every patch site.
- `KYTY_2P_PATCH_NOTES.txt`: what was patched and why, every patched address with its original
  bytes, known limits and a test plan.
- `kyty_2p_listing.txt`: disassembly of every patched site and all new code.

## Known limits

- Player 2's DualSense speaker is not routed.
- `scePadRead` for player 2 returns one sample (the current state), not the queued history.
- Two users are always logged in, even in single-player modes.
- Other system libraries (save data, trophies, network) only know the first user.

## License

GPL-2.0, like Kyty (see `LICENSE`). KytyPS5 is based on Kyty
(https://github.com/InoriRus/Kyty, GPL-2.0 / MIT).

The emulator build this patch targets is a fork whose source is not public. The patched exe in the
Releases page is that build with this patch applied.

Not affiliated with Electronic Arts, Sony or the Kyty authors.
