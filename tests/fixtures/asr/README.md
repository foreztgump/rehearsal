# ASR fixtures (R3 G1/G5 WER + cut-off harness)

Small LibriSpeech `test-clean` utterance set converted to 16 kHz mono 16-bit WAV,
with transcripts used by `scripts/stt-wer.py` for reproducible int8-Parakeet WER.

Source: LibriSpeech, https://www.openslr.org/12, CC-BY-4.0. Attribution:
Vassil Panayotov et al., "Librispeech: an ASR corpus based on public domain audio
books," ICASSP 2015.

These are public benchmark clips, not user audio. The operator's own-voice
end-of-speech cut-off clip used at gate time is not committed; pass it via
`scripts/stt-wer.py --cut-off <wav> "<text>"`.
