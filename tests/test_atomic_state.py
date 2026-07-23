"""R2 — écriture d'état atomique et sérialisée (utils/atomic_state).

Prouve qu'un lecteur ne voit JAMAIS un fichier partiel/corrompu, même sous
écritures concurrentes intensives.
"""
import json
import threading

from utils.atomic_state import save_json_atomic


def test_atomic_write_never_partial(tmp_path):
    target = tmp_path / "state.json"
    save_json_atomic(target, {"n": 0})
    errors = []

    def writer(base):
        for i in range(150):
            save_json_atomic(target, {"n": base * 1000 + i, "payload": "x" * 500})

    def reader():
        for _ in range(400):
            # Sur Windows, un lecteur peut recevoir Access Denied l'instant du
            # os.replace : c'est transitoire, on retente. La VRAIE garantie testée
            # est qu'une lecture RÉUSSIE ne renvoie jamais un JSON tronqué/corrompu.
            for attempt in range(50):
                try:
                    raw = target.read_text(encoding="utf-8")
                except PermissionError:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    errors.append("PARTIAL:" + repr(e))   # ← ça, ce serait grave
                else:
                    assert "n" in data
                break

    threads = [threading.Thread(target=writer, args=(b,)) for b in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"lecture d'un fichier partiel/corrompu: {errors[:3]}"
    # État final toujours un JSON valide
    final = json.loads(target.read_text(encoding="utf-8"))
    assert "n" in final
