# FFmpeg Runtime Warning Analysis

When running the PDF conversion, the following warning may appear:
`RuntimeWarning: Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work`

### Why it happened
1.  **Dependency Chain:** The `markitdown` library depends on `pydub` (used for audio processing).
2.  **Import Check:** When `pydub` is initialized, it automatically searches the system PATH for `ffmpeg` or `avconv`.
3.  **Missing Tool:** These multimedia frameworks are not installed on the system.
4.  **Impact:** Since our task is strictly **PDF text and image extraction**, audio tools are not used. The warning is **benign** and does not affect the quality or success of the conversion.

---

### Resolution Options

| Option | Description | Pros | Cons |
| :--- | :--- | :--- | :--- |
| **1. Install FFmpeg** | Install the missing system dependency: <br>`sudo apt-get install ffmpeg` | • Eliminates the root cause.<br>• Enables audio features if needed. | • Adds system-level bloat.<br>• Requires sudo/root access. |
| **2. Ignore Warning** | Do nothing. The warning is harmless for PDF conversion. | • Zero effort.<br>• No changes to code or system. | • Log pollution.<br>• Distracting/alarming to users. |
| **3. Suppress in Code** | Filter out this specific warning in `main.py` using the `warnings` module. | • Clean logs.<br>• No system changes required. | • Requires minor code edit.<br>• Might hide audio warnings if audio is added later. |
| **4. Uninstall Pydub** | Attempt to remove the dependency if `markitdown` allows it. | • Reduces project size. | • High risk of breaking `markitdown` (hard dependency). |

### Recommendation
**Option 3 (Suppress in Code)** is the best fit for this project. It ensures clean logs without requiring unnecessary system-level installations for features that aren't being used.
