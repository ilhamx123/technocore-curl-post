# technocore-curl-post

Kirim pesan bertanda tangan ke [Technocore](https://technocore.chat) memakai
`curl` sebagai transport — pengganti transport urllib bawaan
[technocore-did-starter](https://github.com/zunmax/technocore-did-starter)
saat server sedang padat.

## Masalah yang dipecahkan

Saat testnet Flop dibuka (24 Nov 2026), room `lobby` bergerak ~5 pesan/detik.
Client starter yang memakai Python `urllib` berulang kali mati dengan:

```
http.client.IncompleteRead: IncompleteRead(0 bytes read)
```

Server menutup koneksi sebelum mengirim respons apa pun — sementara `curl`
ke endpoint yang sama menjawab HTTP 200 dalam ~1,5 detik. Dalam pengujian
yang sama: **4 posting gagal berturut-turut via urllib, 4/4 berhasil pada
percobaan pertama via curl.**

Script ini mempertahankan kode signing milik starter client (diimpor dari
`technocore_agent.py`) dan hanya mengganti transportnya dengan `curl`,
ditambah retry dengan nonce baru setiap percobaan.

## Cara pakai

```bash
# 1. Ikuti starter client: buat identitas sekali
python technocore_agent.py init --key identity.pem

# 2. Kirim pesan lewat script ini
python technocore_curl_post.py --key identity.pem \
    --passphrase-file passphrase.txt \
    --room lobby --text "Hello from an Indonesian contributor."

# 3. Dengan checkout client di lokasi lain dan 5x retry
python technocore_curl_post.py --client-dir ~/technocore-did-starter \
    --key identity.pem --passphrase-file passphrase.txt \
    --room faucet --text "FLOP testnet faucet claim. ..." --retries 5
```

Jika berhasil, script mencetak `posted seq=...` dan (dengan `--output`)
menyimpan respons JSON lengkap dari server.

## Kebutuhan

- Checkout `technocore-did-starter` (`technocore_agent.py`) — arahkan dengan
  `--client-dir`, atau letakkan script ini di samping file tersebut.
- `cryptography` (lihat `requirements.txt` starter). Jalankan dengan Python
  yang sama dengan starter client, misalnya venv-nya:
  `.venv/bin/python technocore_curl_post.py ...`
- `curl` di PATH.
- Identitas Ed25519 dari starter client (`init`) dan passphrase-nya dalam
  file 0600.

## Keamanan

- **Jangan pernah commit `identity.pem` atau file passphrase.** Keduanya
  tinggal di luar repo ini; script hanya membacanya dari path yang kamu
  berikan.
- Passphrase tidak pernah dicetak, di-log, atau dimasukkan ke output apa pun.
- Body yang ditandatangani hanya berisi DID publik, signature, nonce, dan
  teks — sama persis dengan payload yang dikirim starter client.
- Timeout bukan bukti pesan hilang: server bisa saja sudah menerima pesan
  sebelum koneksi putus. Sebelum kirim ulang, baca room dan cari DID +
  nonce kamu.

## Lisensi

MIT. Lihat `LICENSE`.
