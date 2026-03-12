// SearchWindow.swift — Floating search panel controller.
//
// Manages a borderless NSPanel with blur vibrancy background that appears
// centered on screen like Spotlight. Dismisses on Escape or click-outside.

import AppKit
import SwiftUI

// MARK: - Keyable Panel

/// NSPanel subclass that allows borderless panels to become the key window.
///
/// By default, borderless NSPanels return false from canBecomeKeyWindow, which
/// silently prevents makeKeyAndOrderFront from working and blocks all keyboard input.
/// Overriding canBecomeKey / canBecomeMain fixes this.
private final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

// MARK: - Search Window Controller

/// Manages the lifecycle of the floating search NSPanel.
///
/// Creates the panel lazily on first show, positions it centered on the main
/// screen, and handles dismiss-on-outside-click via NSWindowDelegate.
final class SearchWindowController: NSObject {

    private var panel: NSPanel?
    private let appState: AppState

    /// Direct reference to the search NSTextField set by FocusableTextField.onFieldReady.
    /// Used in windowDidBecomeKey for reliable makeFirstResponder without a view-hierarchy scan.
    weak var searchTextField: NSTextField?

    /// Width of the search window in points.
    private let windowWidth: CGFloat = 680
    /// Vertical offset above screen center where the window appears.
    private let screenOffsetRatio: CGFloat = 0.15

    /// - Parameter appState: Shared observable state injected into the SwiftUI hierarchy.
    init(appState: AppState) {
        self.appState = appState
        super.init()
    }

    // MARK: - Show / Hide

    /// Show the search window, creating it if this is the first call.
    ///
    /// Centers the panel on the main display, shifted slightly above center
    /// to mimic Spotlight's placement. Activates the app so the panel receives focus.
    func show() {
        if panel == nil { buildPanel() }
        guard let panel else { return }

        positionPanel(panel)

        // Defer slightly so the menu bar dropdown finishes closing first.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
            guard let self else { return }
            // Switch from .accessory to .regular so the app can become the
            // key application and accept keyboard input in the panel.
            // This is the standard pattern for menu bar apps with search windows.
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
            panel.orderFrontRegardless()
            panel.makeKeyAndOrderFront(nil)
            Task { @MainActor in
                self.appState.isSearchWindowVisible = true
            }
        }
    }

    /// Hide the search window and clear the search state.
    func hide() {
        panel?.orderOut(nil)
        // Switch back to accessory so the app disappears from the Dock and
        // App Switcher again once the search window is closed.
        NSApp.setActivationPolicy(.accessory)
        Task { @MainActor in
            appState.isSearchWindowVisible = false
            appState.searchQuery = ""
            appState.searchResults = []
            appState.selectedResultIndex = -1
            appState.hoveredFileDetail = nil
            appState.hoveredResultId = nil
        }
    }

    /// Toggle visibility — shows if hidden, hides if visible.
    func toggle() {
        if panel?.isVisible == true {
            hide()
        } else {
            show()
        }
    }

    /// Make the search text field the first responder via AppKit.
    ///
    /// Called by the clear button and anywhere else that needs to restore
    /// keyboard focus to the field without relying on SwiftUI @FocusState.
    func focusSearchField() {
        guard let panel, let field = searchTextField else { return }
        panel.makeFirstResponder(field)
    }

    // MARK: - Panel Construction

    /// Build the NSPanel with blur background and SwiftUI content.
    private func buildPanel() {
        let panel = KeyablePanel(
            contentRect: NSRect(x: 0, y: 0, width: windowWidth, height: 80),
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.delegate = self

        // Root SwiftUI content with vibrancy background
        let contentView = SearchRootView()
            .environmentObject(appState)
            .onExitCommand { [weak self] in self?.hide() }

        let hosting = NSHostingView(rootView: contentView)
        hosting.autoresizingMask = [.width, .height]
        panel.contentView = hosting

        self.panel = panel
    }

    /// Center the panel on the main screen, offset upward by screenOffsetRatio.
    private func positionPanel(_ panel: NSPanel) {
        guard let screen = NSScreen.main else { return }
        let screenFrame = screen.visibleFrame
        let x = screenFrame.midX - panel.frame.width / 2
        let y = screenFrame.midY + screenFrame.height * screenOffsetRatio
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }
}

// MARK: - NSWindowDelegate

extension SearchWindowController: NSWindowDelegate {

    /// Window became key — make the search field the first responder.
    ///
    /// We use the stored direct reference rather than a view-hierarchy scan because
    /// makeFirstResponder must succeed immediately and the scan can return nil if
    /// SwiftUI hasn't committed the NSTextField to the layer yet.
    func windowDidBecomeKey(_ notification: Notification) {
        guard let panel else { return }
        if let field = searchTextField {
            // Direct reference — most reliable path
            panel.makeFirstResponder(field)
        } else {
            // Fallback: scan the hierarchy (works after first FocusableTextField render)
            if let field = panel.contentView?.firstTextField() {
                panel.makeFirstResponder(field)
            }
        }
    }

    func windowDidResignKey(_ notification: Notification) {
        hide()
    }
}

// MARK: - Search Root View (with vibrancy background)

/// Wraps SearchView + PreviewView in a blurred vibrancy container with
/// rounded corners, matching macOS Spotlight's visual style.
private struct SearchRootView: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        HStack(spacing: 0) {
            SearchView()
                .environmentObject(appState)
                .frame(width: 680)

            // Preview panel slides in to the right when a file is hovered
            if appState.hoveredFileDetail != nil {
                PreviewView()
                    .environmentObject(appState)
                    .frame(width: 320)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .background(VisualEffectBackground(material: .hudWindow, blendingMode: .behindWindow))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.4), radius: 24, x: 0, y: 8)
        .animation(.easeInOut(duration: 0.2), value: appState.hoveredFileDetail != nil)
    }
}

// MARK: - NSVisualEffectView Wrapper

/// SwiftUI-compatible wrapper for NSVisualEffectView with configurable material.
struct VisualEffectBackground: NSViewRepresentable {

    let material: NSVisualEffectView.Material
    let blendingMode: NSVisualEffectView.BlendingMode

    /// Create the underlying NSVisualEffectView.
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        return view
    }

    /// No dynamic updates needed — material/blendingMode are set once.
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

// MARK: - NSView Helper

private extension NSView {
    /// Depth-first search for the first NSTextField in the view hierarchy.
    func firstTextField() -> NSTextField? {
        if let field = self as? NSTextField { return field }
        for sub in subviews {
            if let found = sub.firstTextField() { return found }
        }
        return nil
    }
}
