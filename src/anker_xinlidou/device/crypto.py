"""与录音豆的 ECDH 会话，以及每个文件的 AES-256-CTR 解密。

密钥协商：ECDH(P-256) → 共享 x 坐标 → HKDF-SHA256(salt={1,2,3}, info={1,2,3}) → 32 字节会话密钥。
文件钥匙：AES-CTR(sessionKey, sessionNonce) 解开，前 14 字节应为 ASCII "soundcored3200"。
音频分片：AES-CTR，IV = nonce[:12] + BE_u32(seq * 10)。

逻辑移植自 MIT 许可的 soundcore-pull，用 cryptography 实现。
"""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class CryptoError(Exception):
    pass


FILE_KEY_MAGIC = b"soundcored3200"


def aes_ctr(data: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    dec = cipher.decryptor()
    return dec.update(data) + dec.finalize()


class DeviceCrypto:
    def __init__(self) -> None:
        self._private = ec.generate_private_key(ec.SECP256R1())
        self._session_key: bytes | None = None
        self._file_keys: dict[int, tuple[bytes, bytes]] = {}

    @property
    def has_session(self) -> bool:
        return self._session_key is not None

    @property
    def public_key(self) -> bytes:
        """未压缩 P-256 公钥（65 字节，0x04 开头）。"""
        return self._private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    def complete_handshake(self, payload: bytes) -> None:
        if len(payload) < 97:
            raise CryptoError("密钥交换回包过短")
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), payload[0:65])
        shared = self._private.exchange(ec.ECDH(), peer)  # P-256 共享 x 坐标，32 字节
        if shared != payload[65:97]:
            raise CryptoError("密钥交换校验失败")
        self._session_key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=bytes([1, 2, 3]), info=bytes([1, 2, 3])
        ).derive(shared)

    def prepare_file(self, payload: bytes) -> tuple[int, int]:
        """解析文件头，解出文件钥匙。返回 (file_id, file_size)。"""
        if self._session_key is None:
            raise CryptoError("还没有会话密钥")
        if len(payload) < 87:
            raise CryptoError("文件头过短")
        file_id = int.from_bytes(payload[0:4], "little")
        file_size = int.from_bytes(payload[4:8], "little")
        nonce = payload[8:24]
        encrypted_key = payload[24:70]
        session_nonce = payload[70:86]
        error_code = payload[86]
        if error_code != 0:
            raise CryptoError(f"录音豆拒绝传输（错误码 {error_code}）")
        plain = aes_ctr(encrypted_key, self._session_key, session_nonce)
        if len(plain) < 46 or plain[:14] != FILE_KEY_MAGIC:
            raise CryptoError("文件钥匙校验失败")
        self._file_keys[file_id] = (plain[14:46], nonce[:12])
        return file_id, file_size

    def decrypt_chunk(self, file_id: int, sequence: int, data: bytes) -> bytes:
        if file_id not in self._file_keys:
            raise CryptoError("没有这个文件的钥匙")
        key, nonce = self._file_keys[file_id]
        counter = (sequence * 10) & 0xFFFFFFFF
        iv = nonce + counter.to_bytes(4, "big")
        return aes_ctr(data, key, iv)

    def clear_file(self, file_id: int) -> None:
        self._file_keys.pop(file_id, None)
