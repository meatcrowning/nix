"""Conservative request-to-tool-family routing for Chatter.

This never decides how to answer.  It only puts likely schemas on the first
request so the model does not spend a generation discovering an obvious tool.
Ambiguous prompts stay on the ordinary core set and can always use get_tools.
"""
import re


# Keep this deliberately small and intent-shaped.  It is not spellchecking the
# prompt; it only repairs the common short forms that would otherwise withhold
# the one schema needed to fulfil an obvious generation request.
_MAKE = r"(?:make|create|g(?:enerate|nerate|enrate)|draw|render|edit)"
_IMAGE = r"(?:images?|pictures?|pics?|photos?|art|artwork|illustrations?)"


def request_tools(prompt, generated_tool=""):
    text = " ".join(str(prompt or "").lower().split())
    out = set()

    if generated_tool == "make_image" or re.search(
            rf"\b{_MAKE}\b.{{0,35}}\b{_IMAGE}\b", text):
        out.add("make_image")
    if generated_tool == "make_video" or re.search(
            r"\b(make|create|generate|animate|render)\b.{0,35}"
            r"\b(video|clip|animation)\b", text):
        out.add("make_video")
    if re.search(r"\b(show|find|fetch|search for)\b.{0,30}"
                 r"\b(image|picture|photo|logo|artwork)\b", text):
        out.update(("search_images", "fetch_image"))
    if re.search(r"\b(screenshot|screen shot|look at (my|the) screen)\b", text):
        out.add("screenshot")

    if re.search(r"\b(music|audio) library\b|\b(library|collection) stats\b|"
                 r"\b(what|which).{0,30}\b(albums?|artists?|tracks?|comps?)\b",
                 text):
        out.add("music_library")
    if re.search(r"\blast\.?fm\b|\bscrobbl", text):
        out.add("lastfm")
    if re.search(r"\b(playing|play|pause|resume|skip|seek|volume|queue)\b.{0,35}"
                 r"\b(song|track|album|music|player|media)?\b", text):
        out.add("control_media")

    if re.search(r"\b(earlier|previous|past|old)\b.{0,30}"
                 r"\b(chat|conversation|session)\b|"
                 r"\b(what|do) (i|you) (said|tell|remember)\b", text):
        out.update(("list_sessions", "read_session"))
    if re.search(r"\b(list|show|pull|download|remove|delete|manage|inspect)\b"
                 r".{0,25}\b(models?|ollama)\b|\bunload (the )?model\b", text):
        out.add("manage_models")

    if re.search(r"\b(background|long[- ]running|job status|job log|transcod|"
                 r"fingerprint|library scan)\b", text):
        out.update(("run_job", "job_status", "job_log", "job_stop"))
    if re.search(r"\b(rename|move|delete|remove)\b.{0,35}"
                 r"\b(file|folder|directory|path)\b|"
                 r"\b(create|make)\b.{0,20}\b(folder|directory)\b", text):
        out.update(("write_file", "edit_file", "move_path", "delete_path",
                    "make_dir"))
    return out
