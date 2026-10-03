# Architecture

## Today
    you speak -> Voxta (action inference) -> Voxta VaM plugin -> BVH Player sets Motion Request
      -> request file -> motion_prompter.py (fast path or LLM, gives every movement a lifetime) -> prompt.txt
      -> ardy_stream.py (ARDY generates 2 s chunks) -> latest_vam.bvh -> BVH Player plays it

    VaMRT_Senses (Person atom) --> text snapshot ----------> Voxta "Context (Slot N)"      (what she knows about her surroundings)
                               --> approach / leave / stare -> Voxta "/event", and "reactions" that call any plugin action
                               --> Follow (dry run): what she would do to stay near the user (reports only)

ARDY needs Python and PyTorch, so it cannot run inside VaM. The VaM plugins are clients of a separate motion server.

## Safety principles
- **Nothing runs forever.** Every movement has a lifetime in the prompter, a runaway guard in the stream (an open-ended movement that keeps moving for
  60 s is cut off) and a freeze-on-stale behaviour in the player. See DURATIONS.md.
- **Leases, not commands.** A long-running behaviour (following) is a command with a 3 s lease that the controller keeps renewing while its conditions
  hold (distance to the user, obstacles, ground, allowed area). If the controller stops, she stops within seconds. See FOLLOW.md.
- **Her own frame.** Commands say "ahead / right of her", so VaM's and ARDY's world coordinates never need calibrating.

## Locomotion (measured, see LOCOMOTION.md)
ARDY accepts a root path as a constraint on the call the stream already makes. She follows it to about 1 cm, but does not control where she faces,
so the follower sends paths from a steering planner (`server/ardy_control.py`) that curve the way a forward walker would turn.

## Direction
1. **Senses** (done, growing): a VaM-side plugin that builds a compact text snapshot of the world and sends it on change. CPU only, no GPU cost.
2. **Follow**: dry run done; next the stream consumes the lease command, the plugin applies root travel with an emergency stop; then Voxta can say
   "walk with me" / "stop".
3. **Mind**: an autonomy loop that turns the snapshot and her goals into an intent, plus instant reflexes in VaM.
4. **Body**: the motion client folded into one plugin, talking to a swappable motion server over a documented protocol, so other generators can be plugged in.
5. **Checking**: automatic quality checks (gait metrics already exist) so verified wordings and behaviours grow without manual rating.

Known: the Voxta VaM plugin shows plain TCP/WebSocket clients work inside VaM plugins; we still need our own test before depending on it.
