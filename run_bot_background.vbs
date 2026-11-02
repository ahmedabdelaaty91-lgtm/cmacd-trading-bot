Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\EXPRESS\.gemini\antigravity\scratch\cmacd_trading_bot"
WshShell.Run """C:\Users\EXPRESS\.local\bin\python3.11.exe"" -u bot.py", 0, False
