# Architecture

## Today
    you speak -> Voxta (action inference) -> VaM Voxta plugin -> BVH Player sets Motion Request
      -> request file -> motion_prompter.py (fast path or LLM) -> prompt.txt
      -> ardy_stream.py (ARDY generates 2 s chunks) -> latest_vam.bvh -> BVH Player plays it

ARDY needs Python and PyTorch, so it cannot run inside VaM. The VaM plugin is a client of a separate motion server.

## Direction
1. **Senses**: a VaM-side plugin that builds a compact text snapshot of the world (her pose, the user, nearby atoms,
   touch, clothing) and sends it on change. Runs on the CPU, no GPU cost.
2. **Mind**: an autonomy loop that turns the snapshot and her goals into an intent, plus instant reflexes in VaM.
3. **Body**: the motion client folded into one plugin, talking to a swappable motion server over a documented protocol,
   so other generators can be plugged in.
4. **Checking**: automatic quality checks so verified wordings and behaviours grow without manual rating.

Known: the Voxta VaM plugin shows plain TCP/WebSocket clients work inside VaM plugins; we still need our own test
before depending on it.
