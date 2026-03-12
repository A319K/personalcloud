// SettingsView.swift — Preferences window for the personalcloud menu bar app.
//
// Allows the user to configure: global hotkey, watch folder, backend URL,
// and launch-at-login. All settings persist via UserDefaults.

import SwiftUI
import AppKit
import ServiceManagement

// MARK: - Settings View

/// Native macOS settings window with tabbed sections.
struct SettingsView: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        TabView {
            GeneralSettingsTab()
                .tabItem { Label("General", systemImage: "gearshape") }
                .environmentObject(appState)

            HotkeySettingsTab()
                .tabItem { Label("Hotkey", systemImage: "keyboard") }

            AdvancedSettingsTab()
                .tabItem { Label("Advanced", systemImage: "wrench.and.screwdriver") }
                .environmentObject(appState)
        }
        .padding(20)
        .frame(minWidth: 440, minHeight: 280)
    }
}

// MARK: - General Tab

private struct GeneralSettingsTab: View {

    @EnvironmentObject var appState: AppState
    @AppStorage("watchFolder") private var watchFolder: String = ""
    @AppStorage("launchAtLogin") private var launchAtLogin: Bool = false

    var body: some View {
        Form {
            Section("Sync") {
                HStack {
                    VStack(alignment: .leading) {
                        Text("Watch Folder")
                            .font(.headline)
                        Text(watchFolder.isEmpty ? "Not configured" : watchFolder)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer()
                    Button("Choose…") { pickFolder() }
                }

                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Watcher Status")
                            .font(.headline)
                        Text(appState.syncStatus?.watcherActive == true ? "Running" : "Stopped")
                            .font(.caption)
                            .foregroundColor(appState.syncStatus?.watcherActive == true ? .green : .secondary)
                    }
                    Spacer()
                    Button(appState.syncStatus?.watcherActive == true ? "Stop" : "Start") {
                        appState.toggleWatcher()
                    }
                }
            }

            Section("Startup") {
                Toggle("Launch at login", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { newValue in
                        setLaunchAtLogin(enabled: newValue)
                    }
            }
        }
        .formStyle(.grouped)
    }

    /// Present an NSOpenPanel to let the user select a new watch folder.
    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Select Folder"
        panel.message = "Choose the folder personalcloud should watch and sync."

        if panel.runModal() == .OK, let url = panel.url {
            watchFolder = url.path
        }
    }

    /// Register or remove the app from macOS login items using ServiceManagement.
    private func setLaunchAtLogin(enabled: Bool) {
        if #available(macOS 13.0, *) {
            do {
                if enabled {
                    try SMAppService.mainApp.register()
                } else {
                    try SMAppService.mainApp.unregister()
                }
            } catch {
                // Silently fail — SMAppService can error if the app is not signed
            }
        }
    }
}

// MARK: - Hotkey Tab

private struct HotkeySettingsTab: View {

    @AppStorage("hotkeyCode") private var hotkeyCode: Int = 3     // 'f'
    @AppStorage("hotkeyModifiers") private var hotkeyModifiers: Int = 1572864  // Cmd+Shift

    @State private var isRecording: Bool = false
    @State private var recordedLabel: String = ""

    var body: some View {
        Form {
            Section("Global Search Hotkey") {
                HStack {
                    Text("Current hotkey")
                        .font(.headline)
                    Spacer()
                    Text(hotkeyDescription)
                        .font(.system(.body, design: .monospaced))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Color.secondary.opacity(0.15))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }

                HStack {
                    Text("Record new hotkey")
                        .font(.headline)
                    Spacer()
                    HotkeyRecorderButton(isRecording: $isRecording) { keyCode, modifiers in
                        hotkeyCode = Int(keyCode)
                        hotkeyModifiers = Int(modifiers.rawValue)
                        isRecording = false
                    }
                }

                Text("Note: Hotkey requires Accessibility permission in System Settings → Privacy & Security → Accessibility.")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Button("Open Accessibility Settings") {
                    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                        NSWorkspace.shared.open(url)
                    }
                }
                .buttonStyle(.link)
            }

            Section {
                Button("Reset to Default (⌘⇧F)") {
                    hotkeyCode = 3
                    hotkeyModifiers = Int(NSEvent.ModifierFlags([.command, .shift]).rawValue)
                }
            }
        }
        .formStyle(.grouped)
    }

    /// Human-readable description of the stored hotkey.
    private var hotkeyDescription: String {
        let mods = NSEvent.ModifierFlags(rawValue: UInt(hotkeyModifiers))
        var parts: [String] = []
        if mods.contains(.control) { parts.append("⌃") }
        if mods.contains(.option)  { parts.append("⌥") }
        if mods.contains(.shift)   { parts.append("⇧") }
        if mods.contains(.command) { parts.append("⌘") }
        parts.append(keyCodeToString(UInt16(hotkeyCode)))
        return parts.joined()
    }

    /// Convert a key code to a displayable character string.
    private func keyCodeToString(_ code: UInt16) -> String {
        let map: [UInt16: String] = [
            0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X",
            8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R",
            16: "Y", 17: "T", 32: "U", 34: "I", 31: "O", 35: "P", 37: "L",
            38: "J", 40: "K", 45: "N", 46: "M",
        ]
        return map[code] ?? "(\(code))"
    }
}

// MARK: - Hotkey Recorder Button

/// An NSViewRepresentable button that captures the next keypress as a hotkey.
private struct HotkeyRecorderButton: NSViewRepresentable {

    @Binding var isRecording: Bool
    var onRecord: (UInt16, NSEvent.ModifierFlags) -> Void

    func makeNSView(context: Context) -> NSButton {
        let button = RecorderButton()
        button.title = isRecording ? "Press keys…" : "Record"
        button.bezelStyle = .rounded
        button.target = context.coordinator
        button.action = #selector(Coordinator.toggle)
        button.onRecord = onRecord
        return button
    }

    func updateNSView(_ nsView: NSButton, context: Context) {
        nsView.title = isRecording ? "Press keys…" : "Record"
        if let recorder = nsView as? RecorderButton {
            recorder.isRecordingMode = isRecording
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject {
        var parent: HotkeyRecorderButton
        init(_ parent: HotkeyRecorderButton) { self.parent = parent }

        @objc func toggle() {
            parent.isRecording.toggle()
        }
    }
}

/// NSButton subclass that intercepts keyDown while in recording mode.
private class RecorderButton: NSButton {

    var isRecordingMode: Bool = false
    var onRecord: ((UInt16, NSEvent.ModifierFlags) -> Void)?

    override var acceptsFirstResponder: Bool { true }

    override func keyDown(with event: NSEvent) {
        guard isRecordingMode else { super.keyDown(with: event); return }
        let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        guard !mods.isEmpty else { return }
        onRecord?(event.keyCode, mods)
    }
}

// MARK: - Advanced Tab

private struct AdvancedSettingsTab: View {

    @EnvironmentObject var appState: AppState
    @AppStorage("backendURL") private var backendURL: String = "http://localhost:8000"
    @State private var testResult: String?
    @State private var isTesting: Bool = false

    var body: some View {
        Form {
            Section("Backend") {
                LabeledContent("API Base URL") {
                    TextField("http://localhost:8000", text: $backendURL)
                        .textFieldStyle(.roundedBorder)
                        .frame(maxWidth: 260)
                }

                HStack {
                    Button("Test Connection") { testConnection() }
                        .disabled(isTesting)

                    if isTesting {
                        ProgressView().scaleEffect(0.7)
                    } else if let result = testResult {
                        Text(result)
                            .font(.caption)
                            .foregroundColor(result.hasPrefix("✓") ? .green : .red)
                    }
                }

                Text("Change this if you run the FastAPI backend on a different host or port.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Section("Status Polling") {
                Button("Refresh Status Now") {
                    Task { await appState.refreshStatus() }
                }
            }
        }
        .formStyle(.grouped)
    }

    private func testConnection() {
        isTesting = true
        testResult = nil
        Task {
            let ok = await APIClient.shared.checkHealth()
            isTesting = false
            testResult = ok ? "✓ Backend reachable" : "✗ Cannot connect"
        }
    }
}
