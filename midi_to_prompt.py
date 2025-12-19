"""
Convert a MIDI file into a text prompt suitable for text-to-image models.

Design goals:
- Map pitch classes (C, D, E, ...) to imagery tokens (color, scene, emotion).
- Use global statistics (register, density, velocity, intervals, polyphony) to infer mood/style words.
- Output a compact but expressive English prompt and save it under prompts/.
- Increase diversity so that different performances (even both in C major) feel noticeably different.
"""

import math
import os
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple, Optional

import mido
from mido import MidiFile

# -----------------------------
# Shared note span structure
# -----------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class NoteSpan:
    note: int
    channel: int
    start: float
    end: float
    velocity: int

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# -----------------------------
# MIDI parsing
# -----------------------------


def parse_midi_to_spans(filepath: str) -> List[NoteSpan]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(filepath)

    mid = MidiFile(filepath)
    tempo = 500000  # default 120 BPM
    current_time = 0.0
    active: Dict[Tuple[int, int], Tuple[float, int]] = {}
    spans: List[NoteSpan] = []

    for msg in mido.merge_tracks(mid.tracks):
        delta_seconds = mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        current_time += delta_seconds

        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue

        if msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)] = (current_time, msg.velocity)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key in active:
                start_time, vel = active.pop(key)
                spans.append(
                    NoteSpan(
                        note=msg.note,
                        channel=msg.channel,
                        start=start_time,
                        end=current_time,
                        velocity=vel,
                    )
                )

    # Close any hanging notes at file end
    for (channel, note), (start_time, vel) in active.items():
        spans.append(
            NoteSpan(
                note=note,
                channel=channel,
                start=start_time,
                end=current_time,
                velocity=vel,
            )
        )

    return spans


# -----------------------------
# Note -> imagery token mapping
# -----------------------------
# 扩充每个音高的意象池，让同一个调性也能多样一些

NATURAL_TOKENS: Dict[str, List[str]] = {
    "C": [
        "soft golden light",
        "sunrise glow",
        "warm candlelight",
        "pale yellow petals",
        "gentle lanterns at dawn",
        "a few white doves gliding in the distance",
    ],
    "D": [
        "fresh green leaves",
        "spring meadow",
        "morning forest",
        "tiny sprouts of grass",
        "moss on old stones",
        "a slow drift of maple leaves in the air",
    ],
    "E": [
        "amber reflections",
        "late afternoon sunlight",
        "warm wooden textures",
        "honey-colored highlights",
        "golden dust in the air",
    ],
    "F": [
        "deep blue shadows",
        "quiet night sky",
        "distant mountains",
        "blue mist between hills",
        "dark indigo clouds",
    ],
    "G": [
        "clear blue water",
        "open sky horizon",
        "gentle ocean waves",
        "lake reflecting the sky",
        "ripples on calm water",
    ],
    "A": [
        "dark crimson petals",
        "glowing embers",
        "dramatic red fabric",
        "ruby reflections",
        "faint sparks in the dark",
    ],
    "B": [
        "indigo smoke",
        "twilight mist",
        "dim city lights",
        "faint neon in the distance",
        "blue-violet haze",
    ],
}

SHARP_TOKENS: Dict[str, List[str]] = {
    "C#": [
        "magenta sparks",
        "vivid neon accents",
        "sharp pink highlights",
        "thin purple laser lines",
    ],
    "D#": [
        "violet haze",
        "mysterious purple glow",
        "ink-like purple clouds",
        "deep lilac flashes",
    ],
    "F#": [
        "sharp lime highlights",
        "electric green lines",
        "acid green strokes",
        "neon chartreuse fragments",
    ],
    "G#": [
        "orange streaks",
        "burning sunset clouds",
        "tangerine flares",
        "amber orange trails",
    ],
    "A#": [
        "cyan flashes",
        "cold turquoise light",
        "ice-blue shards",
        "turquoise neon rings",
    ],
}


def pitch_class(note_number: int) -> str:
    return NOTE_NAMES[note_number % 12]


def note_token_for_pitch_class(pc: str) -> str:
    """Randomly pick one imagery token for a given pitch class."""
    if pc in SHARP_TOKENS:
        pool = SHARP_TOKENS[pc]
    else:
        base = pc.split("#")[0]
        pool = NATURAL_TOKENS.get(base, ["abstract shapes"])

    return random.choice(pool)


# -----------------------------
# Global mood & style analysis
# -----------------------------


def analyze_mood(spans: Iterable[NoteSpan]) -> Dict[str, str]:
    spans = list(spans)
    if not spans:
        return {
            "energy": "quiet and minimal",
            "emotion": "calm and introspective",
            "space": "open composition",
        }

    total_duration = max(s.end for s in spans) - min(s.start for s in spans)
    total_duration = max(total_duration, 1e-6)

    avg_velocity = sum(s.velocity for s in spans) / len(spans)
    density = len(spans) / total_duration  # notes per second

    min_note = min(s.note for s in spans)
    max_note = max(s.note for s in spans)
    pitch_span = max_note - min_note
    center = (min_note + max_note) / 2

    # 能量感
    if avg_velocity < 40:
        energy = "very soft and delicate"
    elif avg_velocity < 80:
        energy = "gentle and expressive"
    else:
        energy = "strong and energetic"

    # 情绪（粗略）
    if density < 1.5 and avg_velocity < 60:
        emotion = "calm and introspective"
    elif density > 4.0 and avg_velocity > 70:
        emotion = "dramatic and intense"
    elif center > 72:
        emotion = "bright and hopeful"
    elif center < 55:
        emotion = "deep and melancholic"
    else:
        emotion = "balanced and lyrical"

    # 空间感：根据音域宽度
    if pitch_span < 10:
        space = "minimal, focused framing"
    elif pitch_span < 24:
        space = "moderately wide scene"
    else:
        space = "wide, cinematic composition"

    return {"energy": energy, "emotion": emotion, "space": space}


def analyze_structure(spans: Iterable[NoteSpan]) -> Dict[str, str]:
    """
    Derive structural tags beyond simple mood to increase diversity:
    - register emphasis (low / mid / high)
    - polyphony / chord density
    - rhythmic character (staccato / legato / mixed)
    - texture density description
    - perceived movement
    """
    spans = list(spans)
    if not spans:
        return {
            "register": "neutral register",
            "polyphony": "simple, minimal texture",
            "rhythm": "almost no rhythmic movement",
            "density": "empty, spacious scene",
            "movement": "static and still",
        }

    start_time = min(s.start for s in spans)
    end_time = max(s.end for s in spans)
    total_duration = max(end_time - start_time, 1e-6)

    # Density
    density_val = len(spans) / total_duration
    if density_val < 1.0:
        density = "sparse phrases with plenty of negative space"
    elif density_val < 3.0:
        density = "moderately busy, balanced rhythm"
    else:
        density = "very dense, continuous motion"

    # Register
    min_note = min(s.note for s in spans)
    max_note = max(s.note for s in spans)
    center = (min_note + max_note) / 2
    if center < 55:
        register = "low, warm register focus"
    elif center > 72:
        register = "high, bright register focus"
    else:
        register = "mid-range register, balanced"

    # Rhythmic character from note durations
    durations = [s.duration for s in spans]
    avg_duration = sum(durations) / len(durations)
    short_notes = sum(1 for d in durations if d < 0.25)
    long_notes = sum(1 for d in durations if d > 1.0)
    short_ratio = short_notes / len(durations)
    long_ratio = long_notes / len(durations)

    if short_ratio > 0.6 and avg_duration < 0.35:
        rhythm = "staccato, percussive motion"
    elif long_ratio > 0.6 and avg_duration > 0.8:
        rhythm = "long, sustained phrases"
    else:
        rhythm = "mixed rhythm with both short and long notes"

    # Polyphony using a sweep over note on/off events
    events: List[Tuple[float, int]] = []
    for s in spans:
        events.append((s.start, 1))
        events.append((s.end, -1))
    events.sort(key=lambda x: x[0])

    active = 0
    max_poly = 0
    area = 0.0
    last_time: Optional[float] = None
    for t, delta in events:
        if last_time is not None and t > last_time:
            area += active * (t - last_time)
        active += delta
        max_poly = max(max_poly, active)
        last_time = t

    avg_poly = area / total_duration if total_duration > 0 else 1.0

    if max_poly <= 1.5:
        polyphony = "single melodic line, almost monophonic"
    elif avg_poly < 2.5:
        polyphony = "occasional chords with clear melody"
    else:
        polyphony = "rich, layered chords and harmonies"

    # Perceived movement mixes density and rhythm
    if "staccato" in rhythm and density_val >= 2.0:
        movement = "restless, flickering motion"
    elif "long, sustained" in rhythm and density_val < 2.0:
        movement = "slow, drifting movement"
    else:
        movement = "steady, flowing movement"

    return {
        "register": register,
        "polyphony": polyphony,
        "rhythm": rhythm,
        "density": density,
        "movement": movement,
    }


def analyze_intervals(spans: Iterable[NoteSpan]) -> Dict[str, str]:
    """
    Look at melodic contour: stepwise vs leaping.
    """
    spans = sorted(list(spans), key=lambda s: (s.start, s.note))
    if len(spans) < 2:
        return {"intervals": "almost no melodic motion"}

    notes = [s.note for s in spans]
    diffs = [abs(notes[i + 1] - notes[i]) for i in range(len(notes) - 1)]
    avg_int = sum(diffs) / len(diffs)
    big_leaps = sum(1 for d in diffs if d >= 7) / len(diffs)

    if avg_int <= 2.5 and big_leaps < 0.1:
        label = "smooth, stepwise melodic motion"
    elif avg_int >= 5.0 or big_leaps > 0.3:
        label = "large melodic leaps, fragmented contour"
    else:
        label = "mixed contour with both steps and leaps"

    return {"intervals": label}


# -----------------------------
# Spans -> prompt
# -----------------------------

def spans_to_prompt(spans: Iterable[NoteSpan], seed: int = None) -> str:
    if seed is not None:
        random.seed(seed)

    spans = list(spans)
    if not spans:
        return (
            "A soft, ethereal abstraction, "
            "like mist evaporating at dawn—"
            "gentle gradients of forgotten colors, "
            "empty spaces that breathe."
        )

    # 更细腻的音高权重计算
    pc_weights: Dict[str, float] = {}
    for s in spans:
        pc = pitch_class(s.note)
        # 加入更多维度：速度影响"强度"，时长影响"存在感"
        weight = s.duration * (0.3 + s.velocity / 150.0)
        # 加入微小随机偏移，避免过于机械
        weight *= (0.9 + random.random() * 0.2)
        pc_weights[pc] = pc_weights.get(pc, 0.0) + weight

    # 选择意象，数量更灵活
    sorted_pcs = sorted(pc_weights.items(), key=lambda x: x[1], reverse=True)
    max_motifs = random.randint(2, 5)  # 更少但更精致
    top_pcs = [pc for pc, _ in sorted_pcs[:max_motifs]]

    # 更诗意的空间表达
    scene_roles = [
        "like whispers in a half-remembered dream",
        "as faint stains on old parchment",
        "hovering at the edge of perception",
        "dissolving into the atmosphere",
        "a distant echo of color",
        "traces left by something that has just departed",
        "ghosts of forgotten moments",
        "barely-there suggestions of form",
    ]

    # 意象修饰词库
    modifiers = [
        "veiled", "gauzy", "translucent", "luminous", "opal", "pearlescent", 
        "silvery", "gilded", "ash", "sepia", "crepuscular", "nocturnal",
        "weathered", "fractured", "diffuse", "radiant", "smudged", "embossed"
    ]

    motif_phrases: List[str] = []
    for pc in top_pcs:
        base_imagery = note_token_for_pitch_class(pc)
        modifier = random.choice(modifiers)
        role = random.choice(scene_roles)
        
        # 构建更诗意的表达
        if random.random() > 0.5:
            phrase = f"{modifier} {base_imagery} {role}"
        else:
            phrase = f"{base_imagery}, {modifier} and {role}"
        
        motif_phrases.append(phrase)
    
    # 微妙地打乱顺序
    motif_phrases = sorted(motif_phrases, key=lambda x: random.random())
    if len(motif_phrases) > 3:
        # 随机保留2-4个，制造留白感
        keep_count = random.randint(2, min(4, len(motif_phrases)))
        motif_phrases = motif_phrases[:keep_count]
    
    # 用更诗意的连接词
    connectors = ["; ", " — ", ", ", "\n"]
    motif_phrase = random.choice(connectors[:-1]).join(motif_phrases)

    # 解析情绪与结构
    mood = analyze_mood(spans)
    struct = analyze_structure(spans)
    intervals = analyze_intervals(spans)

    # 更朦胧的场景类型
    if "low, warm" in struct["register"]:
        possible_scenes = [
            "a chamber of amber light",
            "the bottom of a slow river at twilight",
            "the border where memory turns into mist",
        ]
    elif "high, bright" in struct["register"]:
        possible_scenes = [
            "the afterimage of a star",
            "frost forming on a windowpane at dawn",
            "moonlight caught in spider silk",
            "a scattering of dust motes in a sunbeam",
        ]
    else:
        possible_scenes = [
            "the architecture of silence",
            "a map of faint tremors",
            "the ghost of a gesture",
            "residue of forgotten conversations",
        ]
    scene_type = random.choice(possible_scenes)

    # 更艺术的风格预设（限定为几种明确风格）
    style_presets = [
        # 1. 印象派优化风格
        "optimized impressionist oil painting, soft broken brushstrokes, shimmering light, muted yet rich colors",
        # 2. 神性、纯净的摄影风格
        "divine, pure photography style, soft natural light, high dynamic range, minimal noise, cinematic composition",
        # 3. 梵高笔触风格
        "Van Gogh brushwork style, thick impasto strokes, swirling motion, vibrant contrasting colors",
        # 4. CG建模风格
        "high quality CG 3D rendering, detailed modeling, physically based lighting, crisp edges, realistic materials",
    ]
    style = random.choice(style_presets)

    # 更诗意的模板，强调朦胧和美感
    templates = [
        (
            "{scene_type}. \n"
            "A {emotion} feeling, {energy} in its essence. \n"
            "There is a sense of {movement}, as if something is {intervals}. \n"
            "The air holds {motifs}. \n"
            "Everything is {polyphony} and {rhythm}, {density} and {space}. \n"
            "{style}—no words, only the residue of meaning."
        ),
        (
            "{scene_type} unfolds: \n"
            "It is {emotion}, yet {energy} pulses beneath the surface. \n"
            "{movement} guides the eye through {intervals} of absence and presence. \n"
            "{motifs} emerge, then dissolve. \n"
            "The texture is {polyphony}, the breath is {rhythm}, \n"
            "the weight is {density}, the silence is {space}. \n"
            "{style}, a whisper rendered visible."
        ),
        (
            "Imagine {scene_type}. \n"
            "The atmosphere is {emotion}, charged with {energy}. \n"
            "Forms {movement} through {intervals} of light and shadow. \n"
            "Here, {motifs}. \n"
            "All is {polyphony}, measured in {rhythm}, \n"
            "held in {density}, suspended in {space}. \n"
            "{style}—a poem without language."
        ),
    ]
    template = random.choice(templates)

    # 用更诗意的词汇替换部分分析结果
    mood_map = {
        "calm": "still", "tense": "trembling", "bright": "luminous",
        "dark": "velvety", "empty": "resonant", "full": "saturated"
    }
    
    energy = mood_map.get(mood["energy"], mood["energy"])
    emotion = mood_map.get(mood["emotion"], mood["emotion"])
    space_desc = mood["space"]
    
    # 增加空格和换行，创造阅读的呼吸感
    prompt = template.format(
        scene_type=scene_type,
        energy=energy,
        emotion=emotion,
        movement=struct["movement"],
        motifs=motif_phrase,
        polyphony=struct["polyphony"],
        rhythm=struct["rhythm"],
        density=struct["density"],
        intervals=intervals["intervals"],
        space=space_desc,
        style=style,
    )

    # 随机添加一个"标题"式的开场
    openings = [
        "Memory of a place that never was: ",
        "A pattern left by fading light: ",
        "The quality of light just before forgetting: ",
        "A pause that becomes a landscape: ",
    ]
    
    if random.random() > 0.7:  # 30%的概率添加
        prompt = random.choice(openings) + prompt

    return prompt


# -----------------------------
# MIDI -> prompt file
# -----------------------------


def midi_to_prompt(
    midi_path: str,
    output_dir: str = "prompts",
    seed: int = None,
) -> str:
    spans = parse_midi_to_spans(midi_path)
    prompt = spans_to_prompt(spans, seed=seed)

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(midi_path))[0] or "output"
    out_path = os.path.join(output_dir, f"{base}.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(prompt + "\n")

    return out_path


# -----------------------------
# CLI
# -----------------------------


def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert a MIDI file into a text prompt for text-to-image models."
    )
    parser.add_argument("midi_path", help="Input MIDI file path")
    parser.add_argument(
        "--output_dir",
        default="prompts",
        help="Directory to save the generated prompt file (default: prompts/)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for token variation (optional)",
    )
    args = parser.parse_args()

    out = midi_to_prompt(args.midi_path, output_dir=args.output_dir, seed=args.seed)
    print(f"Saved prompt to {out}")


if __name__ == "__main__":
    _cli()
