// =============================================================================
// Utility Functions
// =============================================================================

/// Parse address string (hex or decimal) to u64
pub(super) fn parse_address(addr_str: &str) -> Result<u64, String> {
    let addr_str = addr_str.trim();

    if addr_str.starts_with("0x") || addr_str.starts_with("0X") {
        u64::from_str_radix(&addr_str[2..], 16).map_err(|e| format!("Invalid hex address: {}", e))
    } else {
        addr_str
            .parse::<u64>()
            .map_err(|e| format!("Invalid decimal address: {}", e))
    }
}

/// Parse data string based on format
pub(super) fn parse_data(data_str: &str, format: &str) -> Result<Vec<u8>, String> {
    match format {
        "hex" => {
            // Remove spaces and 0x prefixes
            let clean_str = data_str
                .replace(" ", "")
                .replace("0x", "")
                .replace("0X", "");
            if (clean_str.len() & 1) != 0 {
                return Err("Hex data must have even number of characters".to_string());
            }

            (0..clean_str.len())
                .step_by(2)
                .map(|i| u8::from_str_radix(&clean_str[i..i + 2], 16))
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| format!("Invalid hex data: {}", e))
        }
        "ascii" => Ok(data_str.as_bytes().to_vec()),
        "words32" => {
            let words: Result<Vec<u32>, _> = data_str
                .split_whitespace()
                .map(|s| {
                    if s.starts_with("0x") || s.starts_with("0X") {
                        u32::from_str_radix(&s[2..], 16)
                    } else {
                        s.parse::<u32>()
                    }
                })
                .collect();

            match words {
                Ok(words) => {
                    let mut data = Vec::new();
                    for word in words {
                        data.extend_from_slice(&word.to_le_bytes());
                    }
                    Ok(data)
                }
                Err(e) => Err(format!("Invalid word32 data: {}", e)),
            }
        }
        "words16" => {
            let words: Result<Vec<u16>, _> = data_str
                .split_whitespace()
                .map(|s| {
                    if s.starts_with("0x") || s.starts_with("0X") {
                        u16::from_str_radix(&s[2..], 16)
                    } else {
                        s.parse::<u16>()
                    }
                })
                .collect();

            match words {
                Ok(words) => {
                    let mut data = Vec::new();
                    for word in words {
                        data.extend_from_slice(&word.to_le_bytes());
                    }
                    Ok(data)
                }
                Err(e) => Err(format!("Invalid word16 data: {}", e)),
            }
        }
        _ => Err(format!("Unsupported data format: {}", format)),
    }
}

/// Format memory data for display
pub(super) fn format_memory_data(data: &[u8], format: &str, base_address: u64) -> String {
    match format {
        "hex" => {
            let mut result = String::new();
            for (i, chunk) in data.chunks(16).enumerate() {
                let addr = base_address + (i * 16) as u64;
                result.push_str(&format!("0x{:08X}: ", addr));

                // Hex bytes
                for (j, byte) in chunk.iter().enumerate() {
                    if j == 8 {
                        result.push(' ');
                    }
                    result.push_str(&format!("{:02X} ", byte));
                }

                // Pad if needed
                if chunk.len() < 16 {
                    let padding = (16 - chunk.len()) * 3 + (if chunk.len() <= 8 { 1 } else { 0 });
                    result.push_str(&" ".repeat(padding));
                }

                // ASCII representation
                result.push_str("| ");
                for byte in chunk {
                    if byte.is_ascii_graphic() || *byte == b' ' {
                        result.push(*byte as char);
                    } else {
                        result.push('.');
                    }
                }
                result.push('\n');
            }
            result
        }
        "binary" => data
            .iter()
            .map(|b| format!("{:08b}", b))
            .collect::<Vec<_>>()
            .join(" "),
        "words32" => {
            let mut result = String::new();
            for (i, chunk) in data.chunks(4).enumerate() {
                if chunk.len() == 4 {
                    let addr = base_address + (i * 4) as u64;
                    let word = u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
                    result.push_str(&format!("0x{:08X}: 0x{:08X}\n", addr, word));
                }
            }
            result
        }
        "words16" => {
            let mut result = String::new();
            for (i, chunk) in data.chunks(2).enumerate() {
                if chunk.len() == 2 {
                    let addr = base_address + (i * 2) as u64;
                    let word = u16::from_le_bytes([chunk[0], chunk[1]]);
                    result.push_str(&format!("0x{:08X}: 0x{:04X}\n", addr, word));
                }
            }
            result
        }
        "ascii" => String::from_utf8_lossy(data).to_string(),
        _ => {
            // Default to hex if unknown format
            format_memory_data(data, "hex", base_address)
        }
    }
}
