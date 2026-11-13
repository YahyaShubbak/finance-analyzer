<#
.SYNOPSIS
    Installs (or updates) the Local Finance Analyzer on Windows.

.DESCRIPTION
    Interactive by default: explains each step and asks before changing
    anything. Safe to run again at any time - it reuses the existing
    environment, keeps your settings as defaults and never deletes
    financial data.

    Start it via install.bat (double-click, or from a terminal):
        install.bat              interactive
        install.bat -Yes         non-interactive, use defaults / previous choices
        install.bat -Help        all options

.PARAMETER Yes
    Don't ask anything; use defaults or the choices of the previous installation.
.PARAMETER DataDir
    Folder for the database, imported statements and backups.
.PARAMETER Port
    Local port the app listens on (default 8420).
.PARAMETER Dev
    Also install development tools (tests, linter).
.PARAMETER NoUv
    Use Python's venv + pip even if uv is installed.
.PARAMETER Shortcut
    Create a Start menu shortcut without asking.
.PARAMETER NoShortcut
    Don't create a Start menu shortcut.
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [string]$DataDir = "",
    [int]$Port = 0,
    [switch]$Dev,
    [switch]$NoUv,
    [switch]$Shortcut,
    [switch]$NoShortcut,
    [switch]$Help
)

# Written for Windows PowerShell 5.1 (preinstalled on Windows 10/11) and
# PowerShell 7. Keep this file ASCII-only: Windows PowerShell 5.1 reads
# scripts without a BOM in the legacy code page.

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ($Help) { Get-Help -Detailed $PSCommandPath; exit 0 }

$RepoRoot    = Split-Path -Parent $PSCommandPath
$BackendDir  = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvDir     = Join-Path $BackendDir ".venv"
$VenvPython  = Join-Path $VenvDir "Scripts\python.exe"
$ConfigFile  = Join-Path $RepoRoot "finance.env"
$AppName     = "finance-analyzer"
$MinPython   = [version]"3.12"
$TotalSteps  = 6

# No console to ask (CI, redirected input) -> behave like -Yes.
$Interactive = -not $Yes
try { if ([Console]::IsInputRedirected) { $Interactive = $false } } catch { Write-Verbose "No console attached." }
if ($env:CI) { $Interactive = $false }

# --- output helpers -------------------------------------------------------------

function Write-Step([int]$n, [string]$text) {
    Write-Host ""
    Write-Host "[$n/$TotalSteps] $text" -ForegroundColor Cyan
}
function Write-Info([string]$text) { Write-Host "  $text" }
function Write-Ok([string]$text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host "  !   $text" -ForegroundColor Yellow }

function Wait-BeforeClose {
    # A double-clicked install.bat closes its window as soon as we exit.
    if ($Interactive) { [void](Read-Host "  Press Enter to close this window") }
}

function Exit-Install([string]$text) {
    Write-Host ""
    Write-Host "Installation stopped: $text" -ForegroundColor Red
    Wait-BeforeClose
    exit 1
}

function Read-Answer([string]$question, [string]$default) {
    if (-not $Interactive) { return $default }
    $answer = Read-Host "  $question [$default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim()
}

function Confirm-Choice([string]$question, [bool]$defaultYes) {
    if (-not $Interactive) { return $defaultYes }
    $hint = "y/N"
    if ($defaultYes) { $hint = "Y/n" }
    while ($true) {
        $answer = Read-Host "  $question [$hint]"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $defaultYes }
        switch -Regex ($answer.Trim().ToLowerInvariant()) {
            '^(y|yes|j|ja)$' { return $true }
            '^(n|no|nein)$'  { return $false }
            default          { Write-Host "  Please answer y or n." }
        }
    }
}

function Get-ConfigValue([string]$name) {
    if (-not (Test-Path -LiteralPath $ConfigFile)) { return "" }
    $line = Get-Content -LiteralPath $ConfigFile -Encoding UTF8 | Where-Object { $_ -match "^$name=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    $value = $line.Substring($name.Length + 1)
    if ($value.Length -ge 2 -and $value.StartsWith("'") -and $value.EndsWith("'")) {
        $value = $value.Substring(1, $value.Length - 2).Replace("\'", "'")
    }
    return $value
}

function Test-PortInUse([int]$p) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $p, $null, $null)
        if ($result.AsyncWaitHandle.WaitOne(300)) { $client.EndConnect($result); return $true }
        return $false
    } catch { return $false } finally { $client.Close() }
}

function Get-CurrentPath {
    # Programs installed by winget/uv are only on PATH for new consoles;
    # re-read it from the registry so this session sees them too.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    return "$machine;$user;$env:USERPROFILE\.local\bin"
}

function Invoke-Native([scriptblock]$command) {
    # Windows PowerShell 5.1 turns anything a native program writes to
    # stderr (uv/pip/npm progress, warnings) into an error record when the
    # output is redirected (CI, logs) - with "Stop" that would abort the
    # installer although the program succeeded. Success is judged by the
    # exit code instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $command } finally { $ErrorActionPreference = $previous }
}

function Invoke-Checked([string]$what, [scriptblock]$command) {
    Invoke-Native $command
    if ($LASTEXITCODE -ne 0) { Exit-Install "$what failed (exit code $LASTEXITCODE) - see the messages above." }
}

function Install-WithWinget([string]$what, [string]$id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Info "Please install $what yourself, then run install.bat again."
        return $false
    }
    Write-Info "It can be installed with:  winget install --id $id -e"
    if ($Interactive -and (Confirm-Choice "Install $what now with winget?" $true)) {
        Invoke-Native { & winget install --id $id -e --accept-source-agreements --accept-package-agreements }
        $env:Path = Get-CurrentPath
        return $true
    }
    return $false
}

# Returns the command (array) of a usable Python >= 3.12, or $null.
function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += , @("py", "-3.13")
        $candidates += , @("py", "-3.12")
        $candidates += , @("py", "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    # The "python" in WindowsApps is only a Microsoft Store shortcut, not Python.
    if ($python -and $python.Source -notlike "*\WindowsApps\*") { $candidates += , @($python.Source) }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $pyArgs = @()
        if ($candidate.Count -gt 1) { $pyArgs = $candidate[1..($candidate.Count - 1)] }
        try {
            $out = Invoke-Native { & $exe @pyArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null }
            if ($LASTEXITCODE -eq 0 -and $out -and ([version]"$out" -ge $MinPython)) { return , $candidate }
        } catch {
            Write-Verbose "Python candidate '$($candidate -join ' ')' is not usable: $_"  # e.g. "py -3.13" not installed
        }
    }
    return $null
}

function Test-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { return $false }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { return $false }
    $v = [version]((Invoke-Native { & node --version }).TrimStart("v"))
    # Vite 8 requires Node 20.19+ or 22.12+.
    return ($v -ge [version]"22.12.0") -or ($v.Major -eq 20 -and $v -ge [version]"20.19.0")
}

# Financial data: only the user (plus SYSTEM and Administrators, who can take
# over any file anyway) may open the data folder. A folder outside the user
# profile, e.g. D:\Finanzen, otherwise inherits "Authenticated Users: Modify"
# from the drive root. SIDs, not names: the names are localized.
$OwnSids = @(
    [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
    "S-1-5-18",      # SYSTEM
    "S-1-5-32-544",  # Administrators
    "S-1-3-0",       # CREATOR OWNER (applies to whoever creates a file, i.e. the user)
    "S-1-3-4"        # OWNER RIGHTS
)

# .NET instead of Get-Acl/Set-Acl: those live in Microsoft.PowerShell.Security,
# which Windows PowerShell 5.1 fails to load when install.bat is started from a
# PowerShell 7 terminal (it inherits PowerShell 7's PSModulePath).
function Get-DirectoryAcl([System.IO.DirectoryInfo]$info) {
    if ($info.PSObject.Methods["GetAccessControl"]) { return $info.GetAccessControl() }  # .NET Framework (5.1)
    return [System.IO.FileSystemAclExtensions]::GetAccessControl($info)                    # .NET (PowerShell 7)
}

# Re-apply a DACL saved as SDDL. Passing the unmodified object from
# GetAccessControl() back to SetAccessControl() writes nothing (.NET only
# persists sections that were changed), so a rollback has to rebuild it.
function Restore-DirectoryAcl([System.IO.DirectoryInfo]$info, [string]$sddl) {
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm($sddl, [System.Security.AccessControl.AccessControlSections]::Access)
    Set-DirectoryAcl $info $acl
}

function Set-DirectoryAcl([System.IO.DirectoryInfo]$info, $acl) {
    if ($info.PSObject.Methods["SetAccessControl"]) { $info.SetAccessControl($acl) }
    else { [System.IO.FileSystemAclExtensions]::SetAccessControl($info, $acl) }
}

function Get-ForeignAccess([string]$dir) {
    $names = @()
    # As SIDs: asking for names would throw on any SID without one.
    $rules = (Get-DirectoryAcl (New-Object System.IO.DirectoryInfo $dir)).GetAccessRules(
        $true, $true, [System.Security.Principal.SecurityIdentifier])
    foreach ($rule in $rules) {
        if ($rule.AccessControlType -ne "Allow") { continue }
        $sid = $rule.IdentityReference.Value
        if ($OwnSids -contains $sid) { continue }
        try { $names += $rule.IdentityReference.Translate([System.Security.Principal.NTAccount]).Value }
        catch { $names += $sid }
    }
    return , @($names | Select-Object -Unique)
}

function Protect-DataDir([string]$dir, [bool]$existed) {
    # Never stops the installation: at worst the folder stays as it was.
    try { $foreign = Get-ForeignAccess $dir }
    catch { Write-Warn ("Could not check who can open " + $dir + ": " + $_.Exception.Message); return }
    if ($foreign.Count -eq 0) { return }
    $info = New-Object System.IO.DirectoryInfo $dir
    # Never on a whole drive (it would cut every other user off from
    # everything on it) or a network share (the server may not know this
    # computer's account, which could lock the user out of their own folder).
    $isRoot = $null -eq $info.Parent
    $isNetwork = $dir.StartsWith("\\") -or ((New-Object System.IO.DriveInfo $info.Root.FullName).DriveType -eq "Network")
    if ($isRoot -or $isNetwork) {
        Write-Warn ("Other users can open " + $dir + ". It is a drive or a network folder, so it is left as it is.")
        return
    }
    # A new folder is made private right away; an existing one only when the
    # user says so in an interactive run, since it may be shared on purpose
    # (-Yes never changes it).
    if ($existed) {
        Write-Warn ("Other users on this computer can open " + $dir + " (" + ($foreign -join ", ") + ").")
        if (-not $Interactive) {
            Write-Info "Left as it is (an existing folder is only changed when you agree; run install.bat without -Yes)."
            return
        }
        if (-not (Confirm-Choice "Make it private (only you can open it)?" $true)) { Write-Warn "Left as it is."; return }
    }
    $before = (Get-DirectoryAcl $info).GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)
    try {
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)  # no inherited rules
        $inherit = [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
        foreach ($sid in $OwnSids[0..2]) {
            $identity = New-Object System.Security.Principal.SecurityIdentifier $sid
            $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule $identity, "FullControl", $inherit, "None", "Allow"))
        }
        Set-DirectoryAcl $info $acl
        # The app must still be able to write there; otherwise undo.
        $probe = Join-Path $dir (".write-test-" + [guid]::NewGuid().ToString("N"))
        [System.IO.File]::WriteAllText($probe, "ok")
        Remove-Item -LiteralPath $probe -Force
        Write-Ok "Data folder is private: only you can open it."
    } catch {
        try { Restore-DirectoryAcl $info $before } catch { Write-Verbose "Restoring the previous permissions failed: $_" }
        Write-Warn ("Could not restrict " + $dir + " (" + $_.Exception.Message + "); its permissions are unchanged.")
    }
}

function ConvertTo-EnvValue([string]$value) {
    # Forward slashes: python-dotenv would turn "\\" (UNC paths) into "\".
    $value = $value.Replace("\", "/").Replace("'", "\'")
    return "'$value'"
}

try {

# --- welcome -----------------------------------------------------------------------

Write-Host "Local Finance Analyzer - installation" -ForegroundColor White
Write-Host ""
Write-Info "This sets up the app in:  $RepoRoot"
Write-Info "What will happen:"
Write-Info "  1. check that Python and Node.js are available"
Write-Info "  2. ask where to keep your data and which port to use"
Write-Info "  3. install the backend's Python packages (into backend\.venv, nothing system-wide)"
Write-Info "  4. build the web interface"
Write-Info "  5. save your settings to finance.env"
Write-Info ""
Write-Info "Only the packages themselves are downloaded (from PyPI and npm)."
Write-Info "Your financial data never leaves this computer."
if ($Interactive) {
    Write-Host ""
    if (-not (Confirm-Choice "Continue?" $true)) { Write-Info "Nothing was changed."; Wait-BeforeClose; exit 0 }
}

# --- 1. requirements -------------------------------------------------------------

Write-Step 1 "Checking requirements"

$UseUv = $false
if (-not $NoUv -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    $UseUv = $true
    Write-Ok "uv found - it will manage Python and the packages."
}

$Python = $null
if (-not $UseUv) {
    $Python = Find-Python
    if ($Python) {
        Write-Ok ("Python found: " + ($Python -join " "))
    } else {
        Write-Warn "Python $MinPython or newer was not found."
        Write-Info "Recommended: install 'uv' - a small tool that downloads the right Python by itself."
        if (Install-WithWinget "uv" "astral-sh.uv") {
            if (Get-Command uv -ErrorAction SilentlyContinue) { $UseUv = $true; Write-Ok "uv installed." }
        }
        if (-not $UseUv) {
            if (Install-WithWinget "Python 3.12" "Python.Python.3.12") { $Python = Find-Python }
            if (-not $Python) {
                Exit-Install "Python $MinPython or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') or install uv, then run install.bat again."
            }
            Write-Ok ("Python found: " + ($Python -join " "))
        }
    }
}

$BuildFrontend = $true
if (Test-Node) {
    Write-Ok ("Node.js " + (Invoke-Native { & node --version }) + " and npm " + (Invoke-Native { & npm --version }) + " found.")
} else {
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Write-Warn ("Node.js " + (Invoke-Native { & node --version }) + " is too old or npm is missing - Node.js 20.19+ or 22.12+ is needed.")
    } else {
        Write-Warn "Node.js is not installed. It is only needed to build the web interface."
    }
    [void](Install-WithWinget "Node.js (LTS)" "OpenJS.NodeJS.LTS")
    if (Test-Node) {
        Write-Ok ("Node.js " + (Invoke-Native { & node --version }) + " found.")
    } elseif (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\index.html")) {
        Write-Warn "Using the web interface that was built earlier (it will not be updated)."
        $BuildFrontend = $false
    } else {
        Exit-Install "Node.js 20.19+ (or 22.12+) is required to build the web interface. Install it from https://nodejs.org/ and run install.bat again."
    }
}

# --- 2. settings -------------------------------------------------------------------

Write-Step 2 "Settings"

$LegacyDb = Join-Path $RepoRoot "data\finance.db"
$MoveLegacy = $false
$KeepLegacy = $false
if ((Test-Path -LiteralPath $LegacyDb) -and -not (Get-ConfigValue "FINANCE_DATA_DIR")) {
    Write-Warn "Found data from an older version inside the program folder ($RepoRoot\data)."
    Write-Info "New versions keep data in your personal data folder, so updating or deleting"
    Write-Info "the program folder can never affect it."
    # An earlier "no" is remembered in finance.env and becomes the default, so
    # -Yes (or a run without a console) never moves the data against it.
    $moveDefault = $true
    if ((Get-ConfigValue "FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER") -eq "true") {
        $moveDefault = $false
        Write-Info "Last time you chose to keep it there."
    }
    if (Confirm-Choice "Move your existing data there now? (recommended; everything is copied and checked first)" $moveDefault) {
        $MoveLegacy = $true
    } else {
        $KeepLegacy = $true
        Write-Info "OK - the data stays where it is and keeps working."
    }
}

if ($KeepLegacy) {
    $DataDirChoice = Join-Path $RepoRoot "data"
} else {
    Write-Info "Your database, imported statements and backups are stored in one folder."
    $previous = Get-ConfigValue "FINANCE_DATA_DIR"
    # %LOCALAPPDATA%\finance-analyzer - the same folder the app uses by default.
    if ($previous) { $previous = $previous.Replace("/", "\") }
    else { $previous = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) $AppName }
    if ($DataDir) { $DataDirChoice = $DataDir } else { $DataDirChoice = Read-Answer "Data folder:" $previous }
    $DataDirChoice = [Environment]::ExpandEnvironmentVariables($DataDirChoice)
    if ($DataDirChoice -eq "~" -or $DataDirChoice.StartsWith("~\") -or $DataDirChoice.StartsWith("~/")) {
        $DataDirChoice = $HOME + $DataDirChoice.Substring(1)
    }
    # Combine() keeps an absolute path as is (Join-Path would glue both together).
    $DataDirChoice = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).Path, $DataDirChoice))

    # Another folder than the one in use is only written into the settings:
    # the data stays where it is, and the app would start empty - to the
    # user, all accounts and bookings gone. (A folder with a database of its
    # own is a choice between two sets of data, and not asked about.)
    $currentDb = Join-Path $previous "finance.db"
    $chosenDb = Join-Path $DataDirChoice "finance.db"
    if (-not $MoveLegacy -and (Test-Path -LiteralPath $currentDb) -and -not (Test-Path -LiteralPath $chosenDb)) {
        Write-Warn "Your data is in $previous"
        Write-Info "The folder you chose has no data. The app would start empty there; your accounts"
        Write-Info "and bookings stay in the old folder, but the app would no longer show them."
        Write-Info "To move your data: stop the app, move everything from the old folder into the"
        Write-Info "new one, then run install.bat again."
        if (-not $Interactive) {
            Exit-Install "Not switching to an empty data folder without being asked. Move your data first, or run install.bat without -Yes and confirm. Nothing was changed."
        }
        if (Confirm-Choice "Start with an empty data folder in $DataDirChoice anyway?" $false) {
            Write-Info "OK - the app starts empty there. Your data stays in $previous"
        } else {
            $DataDirChoice = $previous
            Write-Info "OK - keeping $DataDirChoice"
        }
    }
}

$previousPort = Get-ConfigValue "FINANCE_PORT"
if (-not $previousPort) { $previousPort = "8420" }
while ($true) {
    if ($Port -gt 0) { $portText = "$Port" } else { $portText = Read-Answer "Port (the app will be at http://127.0.0.1:PORT):" $previousPort }
    $parsedPort = 0
    if (-not [int]::TryParse($portText, [ref]$parsedPort) -or $parsedPort -lt 1024 -or $parsedPort -gt 65535) {
        if (-not $Interactive) { Exit-Install "Invalid port: $portText" }
        Write-Warn "Please enter a number between 1024 and 65535."
        $Port = 0
        continue
    }
    if (Test-PortInUse $parsedPort) { Write-Warn "Port $parsedPort is currently in use (if that is the app: it is stopped before anything is replaced)." }
    break
}

$previousOpen = Get-ConfigValue "FINANCE_OPEN_BROWSER"
$OpenBrowser = Confirm-Choice "Open the app in your browser automatically when you start it?" ($previousOpen -ne "false")

$CreateShortcut = $false
if ($Shortcut) { $CreateShortcut = $true }
elseif (-not $NoShortcut) { $CreateShortcut = Confirm-Choice "Add 'Local Finance Analyzer' to the Start menu?" $false }

Write-Host ""
Write-Info "Summary"
$movedNote = ""
if ($MoveLegacy) { $movedNote = "  (existing data will be moved here)" }
Write-Info "  Data folder:   $DataDirChoice$movedNote"
Write-Info "  Address:       http://127.0.0.1:$parsedPort"
Write-Info "  Open browser:  $OpenBrowser"
if ($UseUv) { Write-Info "  Python setup:  uv" } else { Write-Info ("  Python setup:  venv + pip (" + ($Python -join " ") + ")") }
if ($Interactive -and -not (Confirm-Choice "Install with these settings?" $true)) { Write-Info "Nothing was changed."; Wait-BeforeClose; exit 0 }

# --- 3. backend ----------------------------------------------------------------------

Write-Step 3 "Installing the backend (Python packages)"
Set-Location -LiteralPath $BackendDir

# An update while the app runs: Windows keeps the files of a running program
# locked, so replacing its packages stops half-way and leaves an environment
# that neither the old nor the new version can use.
if (Test-Path -LiteralPath $VenvPython) {
    Invoke-Native { & $VenvPython -m app --status *> $null }
    $appStatus = $LASTEXITCODE
    if ($appStatus -eq 0) {
        Write-Warn "The app is running. It has to be stopped before its packages are replaced."
        if (-not (Confirm-Choice "Stop the app now?" $true)) {
            Exit-Install "Close the app (its window, or run.bat --stop), then run install.bat again. The app was not changed."
        }
        Invoke-Native { & $VenvPython -m app --stop }
        if ($LASTEXITCODE -ne 0) {
            Exit-Install "The app could not be stopped. Close its window (or end its Python process in the task manager), then run install.bat again. The app was not changed."
        }
        Write-Info "Start it again when the installation is done."
    } elseif ($appStatus -ne 3 -and (Test-PortInUse $parsedPort)) {
        # (3: not running. Anything else: the old environment can't tell - the port may.)
        if (-not (Confirm-Choice "Port $parsedPort is in use. Is the app stopped? (its files can't be replaced while it runs)" $false)) {
            Exit-Install "Stop the app (close its window), then run install.bat again. The app was not changed."
        }
    }
}

$oldVenv = Join-Path $BackendDir "finance"
if (Test-Path -LiteralPath (Join-Path $oldVenv "Scripts\python.exe")) {
    Write-Warn "backend\finance is the environment of an older version and is no longer used."
    if (Confirm-Choice "Delete it? (it only contains downloaded packages)" $true) {
        Remove-Item -LiteralPath $oldVenv -Recurse -Force
        Write-Ok "Removed."
    }
}

if ($UseUv) {
    Write-Info "uv installs the exact package versions from uv.lock into backend\.venv ..."
    $syncArgs = @("sync", "--locked")
    if (-not $Dev) { $syncArgs += "--no-dev" }
    Invoke-Checked "Installing the Python packages with uv" { & uv @syncArgs }
} else {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Info "Creating the environment backend\.venv ..."
        $exe = $Python[0]
        $pyArgs = @()
        if ($Python.Count -gt 1) { $pyArgs = $Python[1..($Python.Count - 1)] }
        Invoke-Checked "Creating the virtual environment" { & $exe @pyArgs -m venv $VenvDir }
    }
    $req = "requirements.txt"
    if ($Dev) { $req = "requirements-dev.txt" }
    Write-Info "Installing the exact package versions from backend\$req (verified by checksum) ..."
    # "python -m pip": pip.exe cannot upgrade itself on Windows.
    Invoke-Native { & $VenvPython -m pip install --quiet --upgrade pip }
    if ($LASTEXITCODE -ne 0) { Write-Warn "Could not upgrade pip; continuing." }
    Invoke-Checked "Installing the Python packages" { & $VenvPython -m pip install --quiet --prefer-binary --require-hashes -r $req }
}

Invoke-Checked "Checking the backend environment" {
    & $VenvPython -c "import fastapi, sqlmodel, alembic, pymupdf, openpyxl, platformdirs, app.main"
}
Write-Ok "Backend ready."

# --- 4. frontend ----------------------------------------------------------------------

Write-Step 4 "Building the web interface"
if ($BuildFrontend) {
    Set-Location -LiteralPath $FrontendDir
    Write-Info "Installing the exact package versions from package-lock.json ..."
    Invoke-Checked "Installing the web interface packages" { & npm ci --no-audit --no-fund --loglevel=error }
    Write-Info "Building ..."
    Invoke-Checked "Building the web interface" { & npm run build --silent }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\index.html"))) {
        Exit-Install "The build did not produce frontend\dist\index.html."
    }
    Write-Ok "Web interface built."
} else {
    Write-Info "Skipped (Node.js not available) - using the existing build."
}

# --- 5. data & settings -------------------------------------------------------------------

Write-Step 5 "Saving settings"
$dataDirExisted = Test-Path -LiteralPath $DataDirChoice
[void][System.IO.Directory]::CreateDirectory($DataDirChoice)
Protect-DataDir $DataDirChoice $dataDirExisted

if ($MoveLegacy) {
    # The migration detects a running app by its instance lock and by open
    # database connections. An app started before this update has no lock
    # and, until its first page load, no open connection: the port still
    # gives it away.
    if ((Test-PortInUse $parsedPort) -and -not (Confirm-Choice "Port $parsedPort is in use. Is the app stopped? (it must not run while its data is moved)" $false)) {
        Exit-Install "Stop the app (close its window), then run install.bat again. Your data was not moved."
    }
    # Copies, verifies, switches finance.env, and only then deletes the
    # originals. See backend\app\legacy_migration.py.
    Write-Info "Copying your data to $DataDirChoice and checking the copy ..."
    Set-Location -LiteralPath $BackendDir
    # "\." so the argument never ends in a backslash: Windows PowerShell would
    # pass "D:\my data\" as  D:\my data"  (the \" escapes the quote).
    $migrationTarget = Join-Path $DataDirChoice "."
    Invoke-Native { & $VenvPython -m app.legacy_migration --repo-root $RepoRoot --target $migrationTarget }
    if ($LASTEXITCODE -ne 0) {
        Exit-Install "Your data was not moved; it stays in $RepoRoot\data and the app keeps using it."
    }
    Write-Ok "Data moved to $DataDirChoice"
}

$lines = @(
    "# Local Finance Analyzer settings - written by install.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm').",
    "# Re-run install.bat to change them, or edit this file and restart the app."
)
if ($KeepLegacy) {
    # Read back by the next run as the default answer (the app ignores it).
    $lines += "FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER=true"
} else {
    $lines += "FINANCE_DATA_DIR=" + (ConvertTo-EnvValue $DataDirChoice)
}
$lines += "FINANCE_PORT=$parsedPort"
$lines += "FINANCE_OPEN_BROWSER=" + $OpenBrowser.ToString().ToLowerInvariant()
# Everything in finance.env that this script doesn't write itself is kept:
# settings added by hand as the README describes (FINANCE_HOST,
# FINANCE_IMPORTS_DIR, FINANCE_BACKUPS_DIR, ...) and the user's own comments.
# Without them the app would look for backups and originals in another
# folder after an update.
if (Test-Path -LiteralPath $ConfigFile) {
    $managed = '^(FINANCE_DATA_DIR|FINANCE_PORT|FINANCE_OPEN_BROWSER|FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER)='
    $ownComment = '^# (Local Finance Analyzer settings |Re-run .* to change them, or edit this file)'
    # (names in any case, as the app reads them; a byte order mark is dropped)
    $lines += @(Get-Content -LiteralPath $ConfigFile -Encoding UTF8 |
        ForEach-Object { $_.TrimStart([char]0xFEFF) } |
        Where-Object { $_ -notmatch $managed -and $_ -notmatch $ownComment })
}
# UTF-8 without BOM (Set-Content -Encoding UTF8 would add one in PowerShell 5.1).
# Written to a temp file and moved over the old one: after a data move the
# old database is gone, so a half-written finance.env (disk full, power cut)
# would lose FINANCE_DATA_DIR and the app would open an empty default folder.
$configTmp = "$ConfigFile.tmp"
[System.IO.File]::WriteAllText($configTmp, ($lines -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding $false))
Move-Item -LiteralPath $configTmp -Destination $ConfigFile -Force
Write-Ok "Settings saved to finance.env"

if ($CreateShortcut) {
    $programs = [Environment]::GetFolderPath("Programs")
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $programs "Local Finance Analyzer.lnk"))
    $link.TargetPath = Join-Path $RepoRoot "run.bat"
    $link.Arguments = "--open"
    $link.WorkingDirectory = $RepoRoot
    $link.Description = "Analyze your bank statements locally"
    $link.Save()
    Write-Ok "Added to the Start menu (it opens a console window; close it to stop the app)."
}

# --- 6. done ------------------------------------------------------------------------------

Write-Step 6 "Done"
Write-Ok "Installation complete."
Write-Info "Start the app with:   run.bat   (double-click, or from a terminal)"
Write-Info "Then open:            http://127.0.0.1:$parsedPort"
Write-Info "Your data is kept in: $DataDirChoice"
Write-Info "Stop the app by closing its window or pressing Ctrl+C in it."
Set-Location -LiteralPath $RepoRoot
if ($Interactive -and (Confirm-Choice "Start the app now?" $true)) {
    & (Join-Path $RepoRoot "run.bat")
    exit $LASTEXITCODE
}
Wait-BeforeClose

} catch {
    Exit-Install $_.Exception.Message
}
