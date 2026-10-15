Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

$fixturesDir = "c:\Projects\Verbus\tests\fixtures\audio"
if (-not (Test-Path $fixturesDir)) {
    New-Item -ItemType Directory -Path $fixturesDir -Force | Out-Null
}

# 1. Short clip
$shortPath = Join-Path $fixturesDir "short_en.wav"
$synth.SetOutputToWaveFile($shortPath)
$synth.Speak("Hello, this is a test of the Verbum transcription engine.")

# 2. Long clip
$longPath = Join-Path $fixturesDir "long_en.wav"
$synth.SetOutputToWaveFile($longPath)
$synth.Speak("Welcome to Verbum. This is a longer audio sample designed to test transcription of multiple continuous sentences. Speech recognition allows hands free note taking and rapid document drafting directly on your local device.")

# 3. Non-English phrase (spoken phonetically or via multilingual if available)
$nonEnPath = Join-Path $fixturesDir "non_en.wav"
$synth.SetOutputToWaveFile($nonEnPath)
$synth.Speak("Bonjour tout le monde. Ceci est un test en francais.")

$synth.Dispose()
Write-Output "Speech fixtures generated successfully."
