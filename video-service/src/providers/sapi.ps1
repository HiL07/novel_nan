param(
  [Parameter(Mandatory = $true)][string]$TextFile,
  [Parameter(Mandatory = $true)][string]$OutFile,
  [string]$Voice = '',
  [int]$Rate = 0
)
# Windows 自带语音合成（System.Speech，离线）：UTF-8 文本文件 → WAV
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  if ($Voice) { $s.SelectVoice($Voice) }
  $s.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
  $s.SetOutputToWaveFile($OutFile)
  $s.Speak([IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8))
} finally {
  $s.Dispose()
}
