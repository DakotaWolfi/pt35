"""Bulk Type 2 copy rules. Source image remains immutable across destinations."""
from tag_workshop_ndef import parse, tlv
from tag_workshop_raw import checked_image


def image_for(source, destination, mode):
    """Return a destination-capacity image, never source UID/manufacturer pages."""
    if not isinstance(source, dict) or not isinstance(destination, dict):
        raise ValueError("Missing source or destination tag")
    if mode == "raw":
        return checked_image(source["data"], destination["capacity"])
    if mode == "ndef":
        kind, text = parse(source["data"])
        return tlv(kind, text, destination["capacity"])
    raise ValueError("Select RAW or NDEF copying")


def is_empty(data):
    """Only blank or known-empty NDEF is safe for automatic empty-only copies."""
    if not isinstance(data, bytes):
        return False
    if not data or not any(data):
        return True
    try:
        kind, value = parse(data)
        return kind == "Empty"
    except (ValueError, UnicodeError):
        return False


def destination_decision(source, destination, mode, policy, successful_uids):
    if destination["uid"] == source["uid"]:
        return "skip", "Source tag presented — never copy onto source"
    if destination["uid"] in successful_uids:
        return "skip", "UID already written in this session"
    try:
        new_data = image_for(source, destination, mode)
    except (KeyError, TypeError, ValueError) as exc:
        return "skip", "Incompatible: " + str(exc)
    if policy == "empty" and not is_empty(destination["data"]):
        return "skip", "Not empty; preserved"
    if policy not in ("empty", "overwrite"):
        return "skip", "Unknown write policy"
    if new_data == destination["data"]:
        return "same", "Already contains matching data"
    return "write", new_data
