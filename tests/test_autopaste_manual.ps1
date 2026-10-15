$ErrorActionPreference = 'SilentlyContinue'

# Open Notepad and wait for it to fully launch (it's a modern UWP wrapper in Win11)
$notepadProc = Start-Process 'C:\Windows\System32\notepad.exe' -PassThru
Start-Sleep -Milliseconds 1500

# Find the visible notepad with a main window
$target = Get-Process -Name notepad -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1

if (-not $target) {
    Write-Host "ERROR: Could not find Notepad with a window handle"
    exit 1
}
Write-Host "[Step 1] Notepad PID=$($target.Id) HWND=$($target.MainWindowHandle)"

# Focus Notepad window using SendKeys approach (no P/Invoke needed)
Add-Type -AssemblyName Microsoft.VisualBasic
[Microsoft.VisualBasic.Interaction]::AppActivate($target.Id)
Start-Sleep -Milliseconds 400

# Set clipboard
$testText = "VERBUM_PASTE_TEST_OK"
Set-Clipboard -Value $testText
Write-Host "[Step 2] Clipboard set: $testText"

# Fire autopaste.exe detached (exactly as Verbum does)
Start-Process -FilePath "c:\Projects\Verbus\app\bin\autopaste.exe" -ArgumentList "200" -WindowStyle Hidden
Start-Sleep -Milliseconds 600

Write-Host "[Step 3] Autopaste fired"

# Read notepad content via Windows Forms SendKeys select-all + clipboard trick
Add-Type -AssemblyName System.Windows.Forms
[Microsoft.VisualBasic.Interaction]::AppActivate($target.Id)
Start-Sleep -Milliseconds 200

# Select all (Ctrl+A) then copy (Ctrl+C) to read the content
[System.Windows.Forms.SendKeys]::SendWait('^a')
Start-Sleep -Milliseconds 150
[System.Windows.Forms.SendKeys]::SendWait('^c')
Start-Sleep -Milliseconds 300

$resultText = Get-Clipboard
Write-Host "[Step 4] Notepad content from clipboard: '$resultText'"

# Kill notepad
Stop-Process -Id $target.Id -Force -ErrorAction SilentlyContinue
Write-Host "[Step 5] Notepad closed"

if ($resultText -like "*$testText*") {
    Write-Host "`nSUCCESS: autopaste correctly injected text into Notepad"
    exit 0
} else {
    Write-Host "`nFAILURE: text not found. Got: '$resultText'"
    exit 1
}
