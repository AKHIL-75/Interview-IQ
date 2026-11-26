# Speech regression fixture

synthetic_candidate.wav was generated locally on 2026-10-08 with Windows System.Speech, Microsoft Zira Desktop (en-US), default rate. speech_reference.txt is the exact input. No real person's recorded voice or private candidate data is included. This synthetic voice is NOT an Indian-English accent test.

The 33.719-second fixture exercises real PyAV decoding to mono 16 kHz PCM. Tests re-encode it as stereo 48 kHz WebM/Opus, verify duration/metadata and temporary-file cleanup, and mock Azure recognition. These tests make no speech-accuracy claim. Historical benchmark JSON files are retained as evidence only.
