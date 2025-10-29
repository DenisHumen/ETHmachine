use bip39::{Language, Mnemonic};
use hmac::{Hmac, Mac};
use pbkdf2::pbkdf2_hmac;
use secp256k1::{PublicKey, Secp256k1, SecretKey};
use sha2::Sha512;
use tiny_keccak::{Hasher, Keccak};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering, AtomicBool};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use clap::Parser;
use colored::*;
use csv::Writer;
use indicatif::{ProgressBar, ProgressStyle};
use rayon::prelude::*;
use num_traits::identities::Zero;
use rand::RngCore;

const BIP39_PBKDF2_ROUNDS: u32 = 2048;
const BIP39_SALT_MODIFIER: &str = "mnemonic";
const BIP32_SEED_MODIFIER: &[u8] = b"Bitcoin seed";
const BIP32_PRIVDEV: u32 = 0x80000000;
const ETH_DERIVATION_PATH: &str = "m/44'/60'/0'/0";

#[derive(Parser, Debug)]
#[command(name = "eth_nice_address")]
#[command(about = "Fast Ethereum nice address generator in Rust", long_about = None)]
struct Args {
    /// Number of nice wallets to generate
    #[arg(short = 'n', long, default_value = "10")]
    num_wallets: usize,

    /// Config file path (Python config.py)
    #[arg(short = 'c', long, default_value = "../../../../config/config.py")]
    config_path: String,

    /// Output CSV file
    #[arg(short = 'o', long, default_value = "../../../../result/result.csv")]
    output: String,

    /// Number of threads (0 = auto detect)
    #[arg(short = 't', long, default_value = "0")]
    threads: usize,

    /// Display search process
    #[arg(short = 'd', long)]
    display_process: bool,
}

#[derive(Debug, Clone)]
struct Config {
    nice_words: Vec<String>,
    repeated_char_count: usize,
    nice_words_enable: bool,
    repeated_char_enable: bool,
    display_process: bool,
}

impl Config {
    fn from_python_config(path: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        
        let mut nice_words = Vec::new();
        let mut repeated_char_count = 10;
        let mut nice_words_enable = true;
        let mut repeated_char_enable = false;
        let mut display_process = false;
        let mut in_nice_address_block = false;
        
        for line in reader.lines() {
            let line = line?;
            let line = line.trim();
            
            // Parse NICE_ADDRESS_WORDS_ETH array
            if line.starts_with("NICE_ADDRESS_WORDS_ETH") {
                in_nice_address_block = true;
                continue;
            }
            
            if in_nice_address_block {
                if line.contains(']') {
                    in_nice_address_block = false;
                }
                // Extract strings like '0'*10, 'a'*10
                if let Some(start) = line.find('\'') {
                    if let Some(end) = line[start + 1..].find('\'') {
                        let char = &line[start + 1..start + 1 + end];
                        if let Some(mult_pos) = line.find('*') {
                            if let Some(count_str) = line[mult_pos + 1..].split(',').next() {
                                if let Ok(count) = count_str.trim().parse::<usize>() {
                                    nice_words.push(char.repeat(count));
                                }
                            }
                        }
                    }
                }
            }
            
            // Parse other config values
            if line.starts_with("REPEATED_CHAR_COUNT =") {
                if let Some(value) = line.split('=').nth(1) {
                    if let Some(num_str) = value.split('#').next() {
                        if let Ok(num) = num_str.trim().parse() {
                            repeated_char_count = num;
                        }
                    }
                }
            }
            
            if line.starts_with("REPEATED_CHAR_COUNT_enable =") {
                repeated_char_enable = line.contains("True");
            }
            
            if line.starts_with("NICE_ADDRESS_WORDS_enable =") {
                nice_words_enable = line.contains("True");
            }
            
            if line.starts_with("display_the_address_search_process =") {
                display_process = line.contains("True");
            }
        }
        
        Ok(Config {
            nice_words,
            repeated_char_count,
            nice_words_enable,
            repeated_char_enable,
            display_process,
        })
    }
}

/// Derive BIP39 seed from mnemonic
fn mnemonic_to_seed(mnemonic: &str, passphrase: &str) -> [u8; 64] {
    let salt = format!("{}{}", BIP39_SALT_MODIFIER, passphrase);
    let mut seed = [0u8; 64];
    pbkdf2_hmac::<Sha512>(
        mnemonic.as_bytes(),
        salt.as_bytes(),
        BIP39_PBKDF2_ROUNDS,
        &mut seed,
    );
    seed
}

/// Derive BIP32 master key from seed
fn seed_to_master_key(seed: &[u8; 64]) -> ([u8; 32], [u8; 32]) {
    type HmacSha512 = Hmac<Sha512>;
    let mut mac = HmacSha512::new_from_slice(BIP32_SEED_MODIFIER).unwrap();
    mac.update(seed);
    let result = mac.finalize();
    let bytes = result.into_bytes();
    
    let mut key = [0u8; 32];
    let mut chain_code = [0u8; 32];
    key.copy_from_slice(&bytes[..32]);
    chain_code.copy_from_slice(&bytes[32..]);
    
    (key, chain_code)
}

/// Derive child key using BIP32
fn derive_child_key(parent_key: &[u8; 32], parent_chain: &[u8; 32], index: u32) -> ([u8; 32], [u8; 32]) {
    type HmacSha512 = Hmac<Sha512>;
    
    let mut data = Vec::new();
    
    if (index & BIP32_PRIVDEV) != 0 {
        // Hardened key
        data.push(0);
        data.extend_from_slice(parent_key);
    } else {
        // Normal key - use public key
        let secp = Secp256k1::new();
        let secret_key = SecretKey::from_slice(parent_key).unwrap();
        let public_key = PublicKey::from_secret_key(&secp, &secret_key);
        data.extend_from_slice(&public_key.serialize());
    }
    
    data.extend_from_slice(&index.to_be_bytes());
    
    loop {
        let mut mac = HmacSha512::new_from_slice(parent_chain).unwrap();
        mac.update(&data);
        let result = mac.finalize();
        let bytes = result.into_bytes();
        
        let mut key = [0u8; 32];
        let mut chain_code = [0u8; 32];
        key.copy_from_slice(&bytes[..32]);
        chain_code.copy_from_slice(&bytes[32..]);
        
        // Add to parent key
        let key_int = num_bigint::BigUint::from_bytes_be(&key);
        let parent_int = num_bigint::BigUint::from_bytes_be(parent_key);
        let curve_order = num_bigint::BigUint::parse_bytes(
            b"FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141",
            16,
        ).unwrap();
        
        let child_int = (&key_int + &parent_int) % &curve_order;
        
        if &key_int < &curve_order && !child_int.is_zero() {
            let child_bytes = child_int.to_bytes_be();
            let mut final_key = [0u8; 32];
            let offset = 32 - child_bytes.len();
            final_key[offset..].copy_from_slice(&child_bytes);
            return (final_key, chain_code);
        }
        
        // Retry with modified data
        data.clear();
        data.push(1);
        data.extend_from_slice(&bytes[32..]);
        data.extend_from_slice(&index.to_be_bytes());
    }
}

/// Parse derivation path
fn parse_derivation_path(path: &str) -> Vec<u32> {
    path.trim_start_matches("m/")
        .split('/')
        .map(|s| {
            if s.ends_with('\'') {
                BIP32_PRIVDEV + s[..s.len() - 1].parse::<u32>().unwrap()
            } else {
                s.parse::<u32>().unwrap()
            }
        })
        .collect()
}

/// Derive private key from mnemonic using derivation path
fn mnemonic_to_private_key(mnemonic: &str, derivation_path: &str, index: u32) -> [u8; 32] {
    let seed = mnemonic_to_seed(mnemonic, "");
    let (mut key, mut chain) = seed_to_master_key(&seed);
    
    let path = parse_derivation_path(derivation_path);
    for &idx in &path {
        let (new_key, new_chain) = derive_child_key(&key, &chain, idx);
        key = new_key;
        chain = new_chain;
    }
    
    // Derive final key with account index
    let (final_key, _) = derive_child_key(&key, &chain, index);
    final_key
}

/// Get Ethereum address from private key
fn private_key_to_address(private_key: &[u8; 32]) -> String {
    let secp = Secp256k1::new();
    let secret_key = SecretKey::from_slice(private_key).unwrap();
    let public_key = PublicKey::from_secret_key(&secp, &secret_key);
    
    // Get uncompressed public key (remove 0x04 prefix)
    let public_key_bytes = public_key.serialize_uncompressed();
    let public_key_bytes = &public_key_bytes[1..]; // Remove prefix
    
    // Keccak256 hash
    let mut hasher = Keccak::v256();
    hasher.update(public_key_bytes);
    let mut hash = [0u8; 32];
    hasher.finalize(&mut hash);
    
    // Take last 20 bytes and convert to checksum address
    let address_bytes = &hash[12..];
    to_checksum_address(address_bytes)
}

/// Convert address to EIP-55 checksum format
fn to_checksum_address(address: &[u8]) -> String {
    let address_hex = hex::encode(address);
    
    let mut hasher = Keccak::v256();
    hasher.update(address_hex.as_bytes());
    let mut hash = [0u8; 32];
    hasher.finalize(&mut hash);
    let hash_hex = hex::encode(hash);
    
    let mut checksum = String::from("0x");
    for (i, ch) in address_hex.chars().enumerate() {
        if ch.is_ascii_digit() {
            checksum.push(ch);
        } else {
            let hash_char = hash_hex.chars().nth(i).unwrap();
            if hash_char >= '8' {
                checksum.push(ch.to_ascii_uppercase());
            } else {
                checksum.push(ch);
            }
        }
    }
    
    checksum
}

/// Check if address is "nice" based on config
fn is_nice_address(address: &str, config: &Config) -> bool {
    let address_lower = address.to_lowercase().replace("0x", "");
    
    let mut matches = false;
    
    // Check for words
    if config.nice_words_enable {
        for word in &config.nice_words {
            if address_lower.contains(&word.to_lowercase()) {
                matches = true;
                break;
            }
        }
    }
    
    // Check for repeated characters (without backreferences)
    if config.repeated_char_enable && !matches {
        matches = has_repeated_chars(&address_lower, config.repeated_char_count);
    }
    
    matches
}

/// Check if string has N repeated consecutive characters
fn has_repeated_chars(s: &str, count: usize) -> bool {
    if count == 0 {
        return false;
    }
    
    let chars: Vec<char> = s.chars().collect();
    if chars.len() < count {
        return false;
    }
    
    for i in 0..=(chars.len() - count) {
        let first_char = chars[i];
        let mut all_same = true;
        
        for j in 1..count {
            if chars[i + j] != first_char {
                all_same = false;
                break;
            }
        }
        
        if all_same {
            return true;
        }
    }
    
    false
}

#[derive(Clone)]
struct WalletResult {
    mnemonic: String,
    address: String,
    private_key: String,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    
    println!("{}", "=== ETH Nice Address Generator (Rust) ===".bright_cyan().bold());
    println!();
    
    // Load config
    let config_path = Path::new(&args.config_path);
    let config = if config_path.exists() {
        println!("{} {}", "Loading config from:".green(), args.config_path);
        Config::from_python_config(&args.config_path)?
    } else {
        println!("{}", "Config file not found, using defaults".yellow());
        Config {
            nice_words: vec!["0".repeat(10)],
            repeated_char_count: 10,
            nice_words_enable: true,
            repeated_char_enable: false,
            display_process: args.display_process,
        }
    };
    
    println!("{} {}", "Nice words enabled:".green(), config.nice_words_enable);
    println!("{} {}", "Repeated chars enabled:".green(), config.repeated_char_enable);
    if config.nice_words_enable {
        println!("{} {:?}", "Search patterns:".green(), &config.nice_words[..config.nice_words.len().min(5)]);
    }
    if config.repeated_char_enable {
        println!("{} {}", "Repeated char count:".green(), config.repeated_char_count);
    }
    println!();
    
    // Set thread count
    let num_threads = if args.threads == 0 {
        thread::available_parallelism()?.get()
    } else {
        args.threads
    };
    rayon::ThreadPoolBuilder::new()
        .num_threads(num_threads)
        .build_global()?;
    
    println!("{} {}", "Using threads:".green(), num_threads);
    println!("{} {}", "Generating:".green(), args.num_wallets);
    println!();
    
    // Create output file with headers
    let mut writer = Writer::from_path(&args.output)?;
    writer.write_record(&["mnemonic", "wallet_address", "private_key"])?;
    writer.flush()?;
    
    // Progress bar
    let pb = ProgressBar::new(args.num_wallets as u64);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{spinner:.green} [{bar:40.cyan/blue}] {pos}/{len} ({eta}) {msg}")?
            .progress_chars("█▓░"),
    );
    
    // Atomic counters
    let found = Arc::new(AtomicU64::new(0));
    let attempts = Arc::new(AtomicU64::new(0));
    let results: Arc<std::sync::Mutex<Vec<WalletResult>>> = Arc::new(std::sync::Mutex::new(Vec::new()));
    let running = Arc::new(AtomicBool::new(true));
    
    // Spawn statistics monitoring thread
    let attempts_clone = Arc::clone(&attempts);
    let found_clone = Arc::clone(&found);
    let running_clone = Arc::clone(&running);
    
    thread::spawn(move || {
        let start_time = Instant::now();
        let mut last_attempts = 0u64;
        
        loop {
            thread::sleep(Duration::from_secs(60));
            
            if !running_clone.load(Ordering::Relaxed) {
                break;
            }
            
            let current_attempts = attempts_clone.load(Ordering::Relaxed);
            let current_found = found_clone.load(Ordering::Relaxed);
            let elapsed = start_time.elapsed().as_secs_f64();
            
            // Calculate average speed
            let avg_speed = current_attempts as f64 / elapsed;
            
            // Calculate speed for last minute
            let last_minute_speed = (current_attempts - last_attempts) as f64 / 60.0;
            last_attempts = current_attempts;
            
            println!(
                "\n{} {} addr/sec | {} {} addr/sec | {} {} | {} {}",
                "📊 Avg:".bright_cyan().bold(),
                format!("{:.0}", avg_speed).yellow(),
                "⚡ Last min:".bright_cyan().bold(),
                format!("{:.0}", last_minute_speed).yellow(),
                "🎯 Found:".bright_green().bold(),
                current_found.to_string().green(),
                "🔍 Checked:".bright_blue().bold(),
                current_attempts.to_string().blue()
            );
        }
    });
    
    // Generate wallets in parallel
    while found.load(Ordering::Relaxed) < args.num_wallets as u64 {
        let batch_size = (args.num_wallets - found.load(Ordering::Relaxed) as usize).min(num_threads * 100);
        
        let batch_results: Vec<Option<WalletResult>> = (0..batch_size)
            .into_par_iter()
            .map(|_| {
                // Generate random entropy for mnemonic (16 bytes = 12 words)
                let mut entropy = [0u8; 16];
                rand::thread_rng().fill_bytes(&mut entropy);
                
                let mnemonic = Mnemonic::from_entropy_in(Language::English, &entropy)
                    .expect("Failed to generate mnemonic");
                let mnemonic_str = mnemonic.to_string();
                
                attempts.fetch_add(1, Ordering::Relaxed);
                
                let private_key = mnemonic_to_private_key(&mnemonic_str, ETH_DERIVATION_PATH, 0);
                let address = private_key_to_address(&private_key);
                let private_key_hex = hex::encode(private_key);
                
                if is_nice_address(&address, &config) {
                    Some(WalletResult {
                        mnemonic: mnemonic_str,
                        address,
                        private_key: private_key_hex,
                    })
                } else {
                    None
                }
            })
            .collect();
        
        // Collect results
        for result in batch_results.into_iter().flatten() {
            if found.load(Ordering::Relaxed) >= args.num_wallets as u64 {
                break;
            }
            
            results.lock().unwrap().push(result.clone());
            found.fetch_add(1, Ordering::Relaxed);
            pb.inc(1);
            
            if config.display_process {
                pb.set_message(format!(
                    "Found: {} | Attempts: {} | Address: {}",
                    found.load(Ordering::Relaxed),
                    attempts.load(Ordering::Relaxed),
                    &result.address[..10]
                ));
            }
        }
    }
    
    pb.finish_with_message("Generation complete!");
    println!();
    
    // Stop monitoring thread
    running.store(false, Ordering::Relaxed);
    
    // Write results to CSV
    let mut writer = Writer::from_writer(
        std::fs::OpenOptions::new()
            .append(true)
            .open(&args.output)?
    );
    
    for result in results.lock().unwrap().iter() {
        writer.write_record(&[&result.mnemonic, &result.address, &result.private_key])?;
    }
    writer.flush()?;
    
    println!(
        "{} Generated {} nice wallets in {} attempts",
        "✓".green().bold(),
        found.load(Ordering::Relaxed),
        attempts.load(Ordering::Relaxed)
    );
    println!("{} {}", "Results saved to:".green(), args.output);
    
    Ok(())
}
