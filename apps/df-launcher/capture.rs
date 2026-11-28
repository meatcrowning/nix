use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::{self, File};
use std::io::{self, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt};
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{self, Command, ExitStatus};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const GAME_LOGS: &[&str] = &["stdout.log", "stderr.log", "errorlog.txt", "gamelog.txt"];

fn fingerprint(path: &str) -> Option<(u64, u64, i64, i64)> {
    let info = fs::metadata(path).ok()?;
    Some((info.ino(), info.len(), info.mtime(), info.mtime_nsec()))
}

fn describe_exit(result: io::Result<ExitStatus>) -> (String, i32) {
    match result {
        Ok(status) => {
            if let Some(signal) = status.signal() {
                let core = if status.core_dumped() { " (core dumped)" } else { "" };
                (format!("Terminated by signal {signal}{core}"), 128 + signal)
            } else {
                let code = status.code().unwrap_or(1);
                (format!("Exited with code {code}"), code)
            }
        }
        Err(error) => (format!("Launch failed: {error}"), 127),
    }
}

fn oom_kills() -> Option<u64> {
    fs::read_to_string("/proc/vmstat").ok()?.lines()
        .find_map(|line| line.strip_prefix("oom_kill ")?.parse().ok())
}

fn install_activity_observer() -> io::Result<()> {
    for (path, contents) in [
        ("dfhack-config/scripts/df-launcher-ambience.lua", include_str!("ambience.lua")),
        ("dfhack-config/init/dfhack.df-launcher-ambience.init", "# Owned by Dwarf Fortress Launcher.\ndf-launcher-ambience\n"),
    ] {
        let path = Path::new(path);
        fs::create_dir_all(path.parent().unwrap())?;
        let temporary = path.with_extension("new");
        fs::write(&temporary, contents)?;
        fs::rename(temporary, path)?;
    }
    Ok(())
}

fn capture_game(run: &Path, program: OsString, args: impl Iterator<Item = OsString>) -> io::Result<i32> {
    let mut report = File::create(run.join("game.txt"))?;
    writeln!(report, "Executable: {program:?}")?;
    writeln!(report, "LD_PRELOAD: {:?}", env::var_os("LD_PRELOAD"))?;

    let oom_before = oom_kills();
    let mut command = Command::new(program);
    command.args(args);
    let ambience = env::var_os("HOME").map(PathBuf::from)
        .map(|home| home.join(".local/share/df-launcher/ambience.so"));
    if env::var_os("DF_AMBIENCE_FIX").as_deref() != Some(OsStr::new("0")) {
        if let Some(ambience) = ambience.filter(|path| path.is_file()) {
            let mut preload = ambience.into_os_string();
            if let Some(existing) = env::var_os("LD_PRELOAD").filter(|s| !s.is_empty()) {
                preload.push(":");
                preload.push(existing);
            }
            writeln!(report, "Ambience repair preload: {preload:?}")?;
            command.env("LD_PRELOAD", preload);
            // Each run owns its observation file; stale data from another game
            // cannot turn on crowd or depot ambience in this one.
            if Path::new("dfhack-config").is_dir() {
                match install_activity_observer() {
                    Ok(()) => { command.env("DF_AMBIENCE_STATE", run.join("ambience-state.txt")); }
                    Err(error) => { writeln!(report, "Activity observer unavailable: {error}")?; }
                }
            }
        }
    }
    let result = match command.spawn() {
        Ok(mut child) => {
            let maps = format!("/proc/{}/maps", child.id());
            let mut status = None;
            let mut overlay = None;
            for _ in 0..40 {
                if let Ok(contents) = fs::read_to_string(&maps) {
                    if let Some(mapping) = contents.lines().find(|line| line.contains("/gameoverlayrenderer.so")) {
                        overlay = Some(mapping.to_owned());
                        break;
                    }
                }
                status = child.try_wait()?;
                if status.is_some() {
                    break;
                }
                thread::sleep(Duration::from_millis(250));
            }
            let result = match status {
                Some(status) => Ok(status),
                None => child.wait(),
            };
            if let Some(mapping) = overlay {
                writeln!(report, "Overlay mapped: {mapping}")?;
            } else {
                writeln!(report, "Overlay mapping was not observed during startup")?;
            }
            result
        }
        Err(error) => Err(error),
    };
    let (summary, code) = describe_exit(result);
    writeln!(report, "{summary}")?;
    if let (Some(before), Some(after)) = (oom_before, oom_kills()) {
        writeln!(report, "System OOM kills during game: {}", after.saturating_sub(before))?;
    }
    fs::write(run.join("game-result.txt"), format!("Game: {summary}\n"))?;
    Ok(code)
}

fn capture() -> io::Result<i32> {
    let mut args = env::args_os().skip(1);
    let mut program = args.next().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "expected Steam's %command%")
    })?;
    if program == "--capture-game" {
        let run = args.next().ok_or(io::ErrorKind::InvalidInput)?;
        let executable = args.next().ok_or(io::ErrorKind::InvalidInput)?;
        return capture_game(Path::new(&run), executable, args);
    }
    let direct = program == "--direct";
    if direct {
        program = args.next().ok_or(io::ErrorKind::InvalidInput)?;
    }
    let runner = if direct { "Game runtime" } else { "Steam command" };
    let mut args: Vec<_> = args.collect();
    let home = env::var_os("HOME").ok_or(io::ErrorKind::NotFound)?;
    // Use the same home-relative path in Steam's runtime and on the desktop.
    let runs = PathBuf::from(home).join(".local/state/df-launcher/runs");
    fs::DirBuilder::new().recursive(true).mode(0o700).create(&runs)?;
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).map_err(io::Error::other)?;
    let run = runs.join(format!("{:010}.{:09}-{}", timestamp.as_secs(), timestamp.subsec_nanos(), process::id()));
    fs::DirBuilder::new().mode(0o700).create(&run)?;
    let mut report = File::create(run.join("run.txt"))?;
    writeln!(report, "Working directory: {}", env::current_dir()?.display())?;
    writeln!(report, "Command: {program:?}")?;
    let before: Vec<_> = GAME_LOGS.iter().map(|name| fingerprint(name)).collect();
    // Steam's reaper can return success after the game exits on a signal.
    // Leave all runtime arguments in place and wrap the game at its own boundary.
    let game = args.iter().enumerate().find(|(index, argument)| {
        *index > 0 && args[*index - 1] == "--"
            && Path::new(argument).file_name() == Some(OsStr::new("dwarfort"))
    }).map(|(index, _)| index);
    if let Some(index) = game {
        args.splice(index..index, [
            env::current_exe()?.into_os_string(),
            OsString::from("--capture-game"),
            run.clone().into_os_string(),
        ]);
    }
    let result = Command::new(program)
        .args(args)
        .stdout(File::create(run.join("process-stdout.txt"))?)
        .stderr(File::create(run.join("process-stderr.txt"))?)
        .status();
    let (summary, code) = describe_exit(result);
    writeln!(report, "{runner}: {summary}")?;
    let summary = if game.is_some() {
        fs::read_to_string(run.join("game-result.txt"))
            .unwrap_or_else(|_| format!("Game exit unavailable. {runner}: {summary}"))
            .trim_end().to_owned()
    } else {
        format!("{runner}: {summary}")
    };
    for (name, previous) in GAME_LOGS.iter().zip(before) {
        let current = fingerprint(name);
        if current.is_some() && current != previous {
            if let Err(error) = fs::copy(name, run.join(name)) {
                writeln!(report, "Could not archive {name}: {error}")?;
            }
        }
    }
    fs::write(run.join("result.pending"), format!("{summary}\n"))?;
    fs::rename(run.join("result.pending"), run.join("result.txt"))?;
    Ok(code)
}

fn main() {
    match capture() {
        Ok(code) => process::exit(code),
        Err(error) => {
            eprintln!("Dwarf Fortress capture: {error}");
            process::exit(1);
        }
    }
}
