# Redesign notes (new version 2)

**Stop mid-sentence**
- *Tap the orb* while Jarvis is talking: it stops right there (it can talk again next turn).
- *Pause button*: stops it right there and keeps it quiet (text replies still show) until you press Resume.
- Both now flush the audio already queued in the sound card, so it really cuts mid-word. Voice barge-in uses the same flush.

**Orb** - a soft blob-shaped blue orb with a red glow inside and five little "voice pills" that bounce with Jarvis' voice.
Rounded bars, sparks and ripples around it; red ripple where you touch. Drag up/down or scroll = voice volume (ring + % fades out, saved as `voice_volume`).
Caption underneath shows Ready / Listening / Speaking / Thinking.

**Lighter** - the orb is plain QPainter, sleeps completely when idle, glow is cached; top-bar waveform sleeps when quiet;
floating launcher runs at 20 fps instead of 40; painted background instead of the 3D orb (`"live_background": true` brings it back);
short boot fade; no "unlimited fps" browser flags.

**Look** - blue / black / red, softer pill buttons (no outlined boxes), plain-language labels ("Listening", "Online"), Segoe UI.
