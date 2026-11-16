import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;

/** Read-only, transaction-consistent material snapshot. Run with export-materials.ps1. */
public class ExportMaterials {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<String> JSON_FIELDS = Set.of("attributes", "tags", "source", "profile");
    private static final String[] FIELDS = {
        "id", "category", "subtype", "title", "summary", "attributes", "detail", "tags",
        "source", "source_book", "pinned", "merged_into", "profile", "use_count", "create_time", "update_time"
    };

    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Expected: database output-directory");
        Path db = Path.of(args[0]).toAbsolutePath().normalize();
        Path out = Path.of(args[1]).toAbsolutePath().normalize();
        if (!Files.isRegularFile(db)) throw new IOException("Database does not exist: " + db);
        if (!Files.isDirectory(out.getParent())) throw new IOException("Create output parent first");
        Files.createDirectory(out); // Never overwrite an existing export.
        Path partial = out.resolve("materials.jsonl.part");
        Map<String, Long> categories = new TreeMap<>(), kinds = new TreeMap<>();
        long count = 0, active = 0;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        Class.forName("org.sqlite.JDBC");
        // SQLite mode=ro prevents database writes; a single SELECT uses one consistent WAL snapshot.
        try (Connection connection = DriverManager.getConnection("jdbc:sqlite:" + db.toUri() + "?mode=ro")) {
            try (Statement setup = connection.createStatement()) {
                setup.execute("PRAGMA query_only=ON");
                setup.execute("PRAGMA busy_timeout=10000");
            }
            connection.setAutoCommit(false);
            String sql = "SELECT " + String.join(",", FIELDS) + " FROM material ORDER BY id";
            try (Statement statement = connection.createStatement();
                 ResultSet rows = statement.executeQuery(sql);
                 FileOutputStream file = new FileOutputStream(partial.toFile());
                 DigestOutputStream hashed = new DigestOutputStream(file, digest);
                 BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(hashed, StandardCharsets.UTF_8))) {
                while (rows.next()) {
                    Map<String, Object> record = new LinkedHashMap<>();
                    for (String field : FIELDS) {
                        Object value = rows.getObject(field);
                        if (JSON_FIELDS.contains(field) && value != null) {
                            try {
                                value = JSON.readTree(value.toString());
                                if (value == null) throw new IOException("Empty JSON");
                            } catch (IOException e) {
                                throw new IOException("Invalid JSON: material " + rows.getLong("id") + ", field " + field);
                            }
                        }
                        if (field.equals("pinned") && value != null) value = rows.getInt(field) != 0;
                        record.put(camel(field), value);
                    }
                    boolean eligible = rows.getObject("merged_into") == null;
                    record.put("retrievalEligible", eligible);
                    if (eligible) active++;
                    Object source = record.get("source");
                    String kind = source instanceof JsonNode node ? node.path("type").asText("unknown") : "unknown";
                    categories.merge(rows.getString("category"), 1L, Long::sum);
                    kinds.merge(kind, 1L, Long::sum);
                    writer.write(JSON.writeValueAsString(record));
                    writer.write('\n');
                    count++;
                }
                writer.flush();
                file.getFD().sync();
            }
            connection.rollback();
        }
        Files.move(partial, out.resolve("materials.jsonl"), StandardCopyOption.ATOMIC_MOVE);
        Map<String, Object> manifest = new LinkedHashMap<>();
        manifest.put("schemaVersion", 1);
        manifest.put("exportedAt", Instant.now().toString());
        manifest.put("records", count);
        manifest.put("retrievalEligible", active);
        manifest.put("mergedMembers", count - active);
        manifest.put("categories", categories);
        manifest.put("sourceTypes", kinds);
        manifest.put("sha256", HexFormat.of().formatHex(digest.digest()));
        manifest.put("scope", "All confirmed material rows; merged members included for relationship reconstruction. No candidates, credentials, model configs or uploaded books are queried.");
        manifest.put("privacy", "PRIVATE: original material text, excerpts and source names retained; not anonymized. Review before sharing.");
        manifest.put("relationshipPolicy", "Original IDs and nested source/profile objects are preserved. References outside the material table are not exported.");
        Path manifestPart = out.resolve("manifest.json.part");
        Files.writeString(manifestPart, JSON.writerWithDefaultPrettyPrinter().writeValueAsString(manifest) + "\n", StandardCharsets.UTF_8);
        Files.move(manifestPart, out.resolve("manifest.json"), StandardCopyOption.ATOMIC_MOVE);
        System.out.println(JSON.writeValueAsString(manifest));
        System.out.println("Output: " + out);
    }

    private static String camel(String field) {
        StringBuilder result = new StringBuilder();
        boolean upper = false;
        for (char c : field.toCharArray()) {
            if (c == '_') upper = true;
            else { result.append(upper ? Character.toUpperCase(c) : c); upper = false; }
        }
        return result.toString();
    }
}
