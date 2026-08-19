#Requires AutoHotkey v2.0
#SingleInstance Force

; Throwaway spike for specs/ultravnc-input-sink.md's "Prerequisite spike"
; section. Not the production listener -- delete once the spike's answer
; is recorded and the real input-sink.ahk lands.

logPath := A_Args[1]

pid := DllCall("kernel32\GetCurrentProcessId", "UInt")
sessionId := 0
DllCall("kernel32\ProcessIdToSessionId", "UInt", pid, "UInt*", &sessionId)

; Create the log immediately: the driver's readiness check is "the file
; exists", not "a key has been pressed" -- matches the eager-creation
; requirement the real listener will also need.
FileAppend("LISTENER SESSION " sessionId " PID " pid " " A_Now "`n", logPath)

~x::FileAppend("KEY DOWN x SESSION " sessionId " " A_Now "`n", logPath)
~x Up::FileAppend("KEY UP x SESSION " sessionId " " A_Now "`n", logPath)
