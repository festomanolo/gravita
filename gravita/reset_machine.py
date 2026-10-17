    except Exception as e:
        print(f"[gravita] reset_machine: machineid update failed – {e}")
        return False


# ── public entry point ────────────────────────────────────────────────────────

def reset_windsurf_machine_id(verbose: bool = True) -> bool:
    """
    Rotate all Windsurf machine/telemetry IDs.

    Returns True if storage.json was updated, False if Windsurf data is not
    found or writes fail. Always safe to call – skips silently when Windsurf
    is not installed.
    """
    storage = _storage_json()

    if not storage.exists():
        if verbose:
            print(
                f"[gravita] reset_machine: Windsurf storage.json not found "
                f"({storage}) – skipping."
            )
        return False

    if verbose:
        print("[gravita] Rotating Windsurf machine IDs …")

    ids = _generate_ids()

    ok_json   = _update_storage_json(storage, ids)
    ok_sqlite = _update_sqlite(_state_db(), ids) if _state_db().exists() else True
    ok_mid    = _update_machineid(_machineid_file(), ids["_machineid"])

    if verbose:
        if ok_json and ok_sqlite and ok_mid:
            print("[gravita] Windsurf machine IDs rotated successfully.")
        else:
            print("[gravita] Windsurf machine ID rotation completed with some errors (see above).")

    return ok_json


# keep the old name as an alias so nothing else breaks
reset_cursor_machine_id = reset_windsurf_machine_id
