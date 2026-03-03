#!/usr/bin/env python3
"""
Script to install the missing reportlab dependency
"""

import subprocess
import sys
import os

def install_reportlab():
    """Install reportlab package"""
    print("📦 Installing reportlab dependency...")
    
    try:
        # Try to install reportlab
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "reportlab==4.0.7"
        ], capture_output=True, text=True, check=True)
        
        print("✅ reportlab installed successfully!")
        print("Output:", result.stdout)
        
        # Verify installation
        try:
            import reportlab
            print(f"✅ reportlab version {reportlab.Version} is available")
        except ImportError as e:
            print(f"❌ reportlab import failed: {e}")
            return False
            
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install reportlab: {e}")
        print("Error output:", e.stderr)
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def check_requirements():
    """Check if requirements.txt is updated"""
    requirements_file = "requirements.txt"
    
    if not os.path.exists(requirements_file):
        print(f"⚠️  {requirements_file} not found")
        return False
    
    with open(requirements_file, 'r') as f:
        content = f.read()
        
    if "reportlab" in content:
        print("✅ reportlab is already in requirements.txt")
        return True
    else:
        print("⚠️  reportlab is not in requirements.txt")
        print("Please add 'reportlab==4.0.7' to your requirements.txt")
        return False

if __name__ == "__main__":
    print("🔧 EduMaster Answer Key Fix - Dependency Installer")
    print("=" * 50)
    
    # Check requirements.txt
    check_requirements()
    
    # Install reportlab
    success = install_reportlab()
    
    if success:
        print("\n🎉 Installation completed successfully!")
        print("You can now test the answer key export endpoint.")
        print("Run: python test_answer_key_fix.py")
    else:
        print("\n❌ Installation failed!")
        print("Please install reportlab manually:")
        print("pip install reportlab==4.0.7")
