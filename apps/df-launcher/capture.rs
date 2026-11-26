use std::env;
use std::fs::{self, File};
use std::io::{self, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt};
use std::os::unix::process::ExitStatusExt;
use std::path::PathBuf;
use std::process::{self, Command};
use std::time::{SystemTime, UNIX_EPOCH};

const GAME_LOGS: &[&str] = &["stdout.log", "stderr.log", "errorlog.txt", "gamelog.txt"];

fn fingerprint(path: &str) -> Option<(u64, u64, i64, i64)> {
    let info = fs::metadata(path).ok()?;
    Some((info.ino(), info.len(), info.mtime(), info.mtime_nsec()))
}

fn capture() -> io::Result<i32> {
    let mut args = env::args_os().skip(1);
    let program = args.next().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "expected Steam's %command%")
    })?;
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
    let result = Command::new(program)
        .args(args)
        .stdout(File::create(run.join("process-stdout.txt"))?)
        .stderr(File::create(run.join("process-stderr.txt"))?)
        .status();
    let (summary, code) = match result {
        Ok(status) => match status.signal() {
            Some(signal) => (format!("Terminated by signal {signal}"), 128 + signal),
            None => {
                let code = status.code().unwrap_or(1);
                (format!("Exited with code {code}"), code)
            }
        },
        Err(error) => (format!("Launch failed: {error}"), 127),
    };
    writeln!(report, "{summary}")?;
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
