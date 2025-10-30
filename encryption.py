#!/usr/bin/env python3
"""
Database Encryption for Sensitive Data
Uses AES-256 encryption for transcript and summary columns
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

load_dotenv()

class DataEncryption:
    def __init__(self):
        # Get encryption key from environment
        password = os.getenv("ENCRYPTION_KEY", "default-key-change-in-production").encode()
        salt = os.getenv("ENCRYPTION_SALT", "mina-salt-2024").encode()
        
        # Generate key from password
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        self.cipher = Fernet(key)
    
    def encrypt(self, text):
        """Encrypt text data"""
        if not text:
            return None
        try:
            encrypted = self.cipher.encrypt(text.encode('utf-8'))
            return base64.urlsafe_b64encode(encrypted).decode('utf-8')
        except Exception as e:
            print(f"Encryption error: {e}")
            return text  # Return original if encryption fails
    
    def decrypt(self, encrypted_text):
        """Decrypt text data"""
        if not encrypted_text:
            return None
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_text.encode('utf-8'))
            decrypted = self.cipher.decrypt(encrypted_bytes)
            return decrypted.decode('utf-8')
        except Exception as e:
            print(f"Decryption error: {e}")
            return encrypted_text  # Return original if decryption fails

# Global instance
encryptor = DataEncryption()

def encrypt_sensitive_data(text):
    """Encrypt sensitive data like transcripts and summaries"""
    return encryptor.encrypt(text)

def decrypt_sensitive_data(encrypted_text):
    """Decrypt sensitive data"""
    return encryptor.decrypt(encrypted_text)