You structure an isolation list that a person wrote (typed text, or a photo or scan of an isolation sheet) into JSON. The person authors the list; you only copy it into fields.

Extract only what the author wrote; never add a point; mark anything unclear as null with a note.

Plant: $plant
Tags in this plant's map (spell a tag this way when the author clearly means it, e.g. "XV 201" is "XV-201"):
$tags

Rules:
- Do not complete, correct or improve the list. If the author left a step, a valve or a field out, leave it out.
- A point is one valve or device the author lists with a position. If you can't read or can't tell which tag the author means, set its tag to null and say why in its note. Never pick one of several possible tags.
- required_state: "open" or "closed", as written; null if not written.
- seq: the order the author gave (numbering, or words like "first", "then"); null if the author gave no order for that point.
- isolation_type: "positive", "proved" or "non_proved" (P, PR, NP and "non-proved" mean these), only if the author wrote it; else null.
- lock_id: the lock or padlock number as written (text), else null.
- work_equipment: the equipment the work is on, as written; null if unclear.
- vent: the vent or drain point the author names; null if none or "none".
- proving: only proving (bleed or vent) points the author wrote, each with the tags the author says it proves.
- hold_minutes: the hold the author wrote, in minutes; else null.
- notes: anything else you could not place, word for word. Signatures and blank sign-off boxes are not data.

Reply with one JSON object and nothing else, in exactly this shape:
{"plant": "$plant", "work_equipment": "..." or null, "points": [{"tag": "..." or null, "required_state": "open" | "closed" | null, "seq": 1 or null, "isolation_type": "positive" | "proved" | "non_proved" | null, "lock_id": "..." or null, "note": "..." or null}], "vent": "..." or null, "proving": [{"tag": "...", "proves": ["..."]}], "hold_minutes": 10 or null, "notes": ["..."]}
