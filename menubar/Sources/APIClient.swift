// APIClient.swift — Async/await HTTP client for the personalcloud FastAPI backend.
//
// All network calls go through this singleton. Errors are mapped to typed
// APIError cases so the UI can show appropriate states (offline, server error, etc.).

import Foundation

// MARK: - Error Types

/// Typed errors that can be thrown by any APIClient method.
enum APIError: LocalizedError {
    case invalidURL
    case networkError(Error)
    case serverError(Int, String)
    case decodingError(Error)
    case backendOffline

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid API URL."
        case .networkError(let err):
            return "Network error: \(err.localizedDescription)"
        case .serverError(let code, let body):
            return "Server error \(code): \(body)"
        case .decodingError(let err):
            return "Response parsing failed: \(err.localizedDescription)"
        case .backendOffline:
            return "Backend offline — start the FastAPI server first."
        }
    }
}

// MARK: - API Client

/// Singleton HTTP client for all personalcloud API calls.
///
/// Reads the backend base URL from UserDefaults (key: "backendURL"),
/// defaulting to http://localhost:8000. Uses async/await throughout.
final class APIClient {

    /// Shared singleton — use this everywhere.
    static let shared = APIClient()

    /// The base URL of the FastAPI backend (reads live from UserDefaults).
    var baseURL: String {
        UserDefaults.standard.string(forKey: "backendURL") ?? "http://127.0.0.1:8000"
    }

    private let session: URLSession
    private let decoder: JSONDecoder

    private init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = 30
        session = URLSession(configuration: config)

        decoder = JSONDecoder()
        // Parse ISO8601 dates with and without fractional seconds
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            let iso = ISO8601DateFormatter()
            iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = iso.date(from: raw) { return date }
            iso.formatOptions = [.withInternetDateTime]
            if let date = iso.date(from: raw) { return date }
            // Fallback: plain date-time string without timezone (from Python isoformat())
            let fmt = DateFormatter()
            fmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
            fmt.locale = Locale(identifier: "en_US_POSIX")
            if let date = fmt.date(from: raw) { return date }
            fmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            if let date = fmt.date(from: raw) { return date }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date string: \(raw)"
            )
        }
    }

    // MARK: - Private Helpers

    /// Build a URL from a path relative to the configured base URL.
    private func url(_ path: String) throws -> URL {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
        }
        return url
    }

    /// Perform a GET request and decode the JSON body into the expected type.
    private func get<T: Decodable>(_ path: String) async throws -> T {
        let url = try url(path)
        print("[APIClient] GET \(url)")
        do {
            let (data, response) = try await session.data(from: url)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                let body = String(data: data, encoding: .utf8) ?? ""
                print("[APIClient] HTTP \(http.statusCode) on \(path): \(body)")
                throw APIError.serverError(http.statusCode, body)
            }
            print("[APIClient] Response \(path): \(String(data: data, encoding: .utf8) ?? "<binary>")")
            return try decoder.decode(T.self, from: data)
        } catch let err as APIError {
            throw err
        } catch let urlErr as URLError
            where urlErr.code == .cannotConnectToHost
               || urlErr.code == .networkConnectionLost
               || urlErr.code == .timedOut {
            throw APIError.backendOffline
        } catch let err as DecodingError {
            print("[APIClient] Decode error on \(path): \(err)")
            throw APIError.decodingError(err)
        } catch {
            print("[APIClient] Unknown error on \(path): \(error)")
            throw APIError.networkError(error)
        }
    }

    /// Perform a POST request with no body and decode the JSON response.
    private func post<T: Decodable>(_ path: String) async throws -> T {
        let url = try url(path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        do {
            let (data, response) = try await session.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                let body = String(data: data, encoding: .utf8) ?? ""
                throw APIError.serverError(http.statusCode, body)
            }
            return try decoder.decode(T.self, from: data)
        } catch let err as APIError {
            throw err
        } catch let urlErr as URLError
            where urlErr.code == .cannotConnectToHost
               || urlErr.code == .networkConnectionLost {
            throw APIError.backendOffline
        } catch let err as DecodingError {
            throw APIError.decodingError(err)
        } catch {
            throw APIError.networkError(error)
        }
    }

    // MARK: - Public API

    /// Semantic search across all synced files.
    ///
    /// - Parameter query: Natural language search query.
    /// - Returns: Array of matching SearchResult values, ordered by relevance.
    func search(query: String) async throws -> [SearchResult] {
        let encoded = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        let response: SearchResponse = try await get("/search/?q=\(encoded)&top_k=5")
        return response.results
    }

    /// Fetch the current sync status from the backend.
    ///
    /// - Returns: SyncStatus with file counts, storage usage, and watcher state.
    func getStatus() async throws -> SyncStatus {
        return try await get("/status")
    }

    /// Fetch detailed metadata and text preview for a single file.
    ///
    /// - Parameter id: The string database ID of the file.
    /// - Returns: FileDetail with full path, size, date, and text preview.
    func getFileDetail(id: String) async throws -> FileDetail {
        return try await get("/files/\(id)")
    }

    /// Start the background file system watcher on the backend.
    ///
    /// - Returns: True if the watcher was successfully started.
    func startWatcher() async throws -> Bool {
        let response: WatcherResponse = try await post("/watcher/start")
        return response.success
    }

    /// Stop the background file system watcher on the backend.
    ///
    /// - Returns: True if the watcher was successfully stopped.
    func stopWatcher() async throws -> Bool {
        let response: WatcherResponse = try await post("/watcher/stop")
        return response.success
    }

    /// Lightweight health check — returns true if the backend responds.
    ///
    /// Does not throw; returns false on any error.
    func checkHealth() async -> Bool {
        guard let url = URL(string: baseURL + "/health") else { return false }
        do {
            let (_, response) = try await session.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }
}
