"""Writes signal-registry-1.9.0.json from 1.8.0.

1.9.0 (additive): console input, from ApiUsageExtractor (step 3 scanner
1.4.0). A console application that needs a person at the keyboard is an
interactive tool, not a batch job (catalog item interactive-console-tool);
console-batch-job excludes it. A discarded read ("Press ENTER to exit")
is recorded separately: with no console it returns at once, so it does not
prove a person is needed.
Run from this folder:  python make_signal_registry_1_9_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.8.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.9.0"


def signal(name, description, value):
    return {
        "name": name,
        "category": "EXECUTION_INDICATOR",
        "type": "API_INVOCATION",
        "description": description,
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": value,
    }


registry["signals"] += [
    signal("INTERACTIVE_CONSOLE_INPUT",
           "The program needs a person at the keyboard: Console.ReadKey (which throws when there is no console or input is "
           "redirected), a Console.Read or ReadLine whose result is used, or an interactive prompt library (Spectre.Console "
           "prompts, Sharprompt). A scheduled or containerised job has no one to answer it.",
           "the member ('System.Console.ReadKey', 'System.Console.ReadLine', 'Spectre.Console.TextPrompt', "
           "'Sharprompt.Prompt.Select'); one row per member per file, a line span per use."),
    signal("CONSOLE_PAUSE_FOR_INPUT",
           "A Console.Read or ReadLine whose result is discarded: 'Press ENTER to exit', or a self-hosted service waiting to be "
           "stopped. With no console it returns at once rather than blocking, so it does not prove a person is needed — but a "
           "host that waits on it to stay alive exits immediately in a container.",
           "the member ('System.Console.ReadLine'); one row per member per file, a line span per use."),
]

out = HERE / "signal-registry-1.9.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
