use deflate_core::DEFAULT_LIMIT;
use deflate_core::zip::{
    CompressionMethod, find_end_central_dir, read_central_dir_header, read_end_central_dir,
    unzip_single, zip_single,
};

fn main() {
    let data = b"hello world hello world hello world";
    let file_name = b"test.txt";
    let zip = zip_single(file_name, data, CompressionMethod::Deflate).unwrap();
    println!("ZIP size: {}", zip.len());
    println!("ZIP hex: {:02x?}", &zip[..std::cmp::min(zip.len(), 200)]);

    // Try to find EOCD
    let eocd_offset = find_end_central_dir(&zip);
    println!("EOCD offset: {:?}", eocd_offset);

    if let Some(offset) = eocd_offset {
        let eocd = read_end_central_dir(&zip[offset..]).unwrap();
        println!("EOCD: {:?}", eocd);

        let cd_offset = eocd.cd_offset as usize;
        println!("CD offset: {}", cd_offset);
        println!("CD size: {}", eocd.cd_size);

        if cd_offset + eocd.cd_size as usize <= zip.len() {
            let cd_data = &zip[cd_offset..cd_offset + eocd.cd_size as usize];
            println!("CD data size: {}", cd_data.len());
            println!(
                "CD data hex: {:02x?}",
                &cd_data[..std::cmp::min(cd_data.len(), 200)]
            );

            let (cd_header, cd_size) = read_central_dir_header(cd_data).unwrap();
            println!("CD header: {:?}", cd_header);
            println!("CD header size: {}", cd_size);
        } else {
            println!("CD offset + size exceeds ZIP length!");
        }
    }

    match unzip_single(&zip, DEFAULT_LIMIT) {
        Ok((decompressed, name)) => {
            println!("Decompressed: {:?}", String::from_utf8_lossy(&decompressed));
            println!("Name: {:?}", String::from_utf8_lossy(&name));
        }
        Err(e) => println!("Error: {:?}", e),
    }
}
