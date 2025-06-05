import ftplib
import sys
from config import FTP_CONFIG

def test_ftp_connection():
    """Test the FTP connection separately from the Flask application"""
    print("FTP Connection Test")
    print("-" * 40)
    print(f"Host: {FTP_CONFIG['host']}")
    print(f"Username: {FTP_CONFIG['username']}")
    print(f"Password: {'*' * len(FTP_CONFIG['password'])}")
    print(f"Port: {FTP_CONFIG['port']}")
    print(f"Base Path: {FTP_CONFIG['base_path']}")
    print(f"Use SFTP: {FTP_CONFIG['use_sftp']}")
    print("-" * 40)
    
    # Fix FTP host if it includes protocol
    ftp_host = FTP_CONFIG['host']
    if ftp_host.startswith('ftp://'):
        ftp_host = ftp_host[6:]  # Remove 'ftp://' prefix
    
    try:
        # Connect to server
        print(f"Connecting to FTP server {ftp_host}:{FTP_CONFIG['port']}...")
        ftp = ftplib.FTP()
        ftp.connect(ftp_host, FTP_CONFIG['port'])
        print("✓ FTP server connection established")
        
        # Try login with provided credentials
        print(f"Attempting login with username: {FTP_CONFIG['username']}")
        
        # First try - standard login
        try:
            ftp.login(FTP_CONFIG['username'], FTP_CONFIG['password'])
            print("✓ Login successful with standard username")
            login_successful = True
        except Exception as e:
            print(f"✗ Standard login failed: {str(e)}")
            login_successful = False
        
        # If standard login failed, try alternative formats
        if not login_successful:
            print("Trying alternative username formats...")
            
            # Some servers require username@domain.com format
            if '@' not in FTP_CONFIG['username'] and '.' in ftp_host:
                alt_username = f"{FTP_CONFIG['username']}@{ftp_host}"
                try:
                    ftp = ftplib.FTP()
                    ftp.connect(ftp_host, FTP_CONFIG['port'])
                    ftp.login(alt_username, FTP_CONFIG['password'])
                    print(f"✓ Login successful with alternative username: {alt_username}")
                    login_successful = True
                except Exception as e:
                    print(f"✗ Alternative login failed with {alt_username}: {str(e)}")
            
            # Try with domain.com\username format (Windows FTP servers)
            try:
                alt_username = f"{ftp_host}\\{FTP_CONFIG['username']}"
                ftp = ftplib.FTP()
                ftp.connect(ftp_host, FTP_CONFIG['port'])
                ftp.login(alt_username, FTP_CONFIG['password'])
                print(f"✓ Login successful with Windows-style username: {alt_username}")
                login_successful = True
            except Exception as e:
                print(f"✗ Windows-style login failed: {str(e)}")
        
        if not login_successful:
            print("❌ All login attempts failed")
            return False
            
        # Print current directory
        current_dir = ftp.pwd()
        print(f"Current directory: {current_dir}")
        
        # List directory contents
        print("Directory listing:")
        files = []
        ftp.dir(files.append)
        for file in files[:10]:  # Show first 10 files
            print(f"  {file}")
        
        # Try to change to the target directory
        target_dir = FTP_CONFIG['base_path']
        try:
            print(f"Changing to directory: {target_dir}")
            ftp.cwd(target_dir)
            print(f"✓ Successfully changed to: {ftp.pwd()}")
            
            # List contents of the target directory
            print(f"Contents of {target_dir}:")
            target_files = []
            ftp.dir(target_files.append)
            for file in target_files[:10]:  # Show first 10 files
                print(f"  {file}")
        except Exception as e:
            print(f"✗ Error changing to target directory: {str(e)}")
        
        # Test write permission by creating a small test file
        try:
            print("Testing write permission...")
            test_data = "This is a test file to verify FTP write permissions."
            from io import BytesIO
            test_file = BytesIO(test_data.encode())
            ftp.storbinary('STOR test_upload.txt', test_file)
            print("✓ Successfully uploaded test file")
            
            # Try to delete the test file
            try:
                ftp.delete('test_upload.txt')
                print("✓ Successfully deleted test file")
            except Exception as e:
                print(f"✗ Could not delete test file: {str(e)}")
        except Exception as e:
            print(f"✗ Could not upload test file: {str(e)}")
            
        # Close connection
        ftp.quit()
        print("FTP connection closed successfully")
        return True
    
    except Exception as e:
        # Handle any connection errors
        print(f"❌ FTP connection error: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_ftp_connection()
    print("-" * 40)
    if success:
        print("✅ FTP TEST SUCCESSFUL")
    else:
        print("❌ FTP TEST FAILED")
        print("Please check your FTP configuration in config.py") 