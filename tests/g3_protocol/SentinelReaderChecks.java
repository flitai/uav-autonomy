package validation.g3;

import afrl.cmasi.KeyValuePair;
import avtas.amase.network.SentinelMessageReader;
import avtas.lmcp.LMCPFactory;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/** Real generated LMCP plus the production TCP reader; no alternate decoder. */
public final class SentinelReaderChecks {
    private static void require(boolean value) {
        if (!value) throw new AssertionError("Sentinel reader check failed");
    }

    public static void main(String[] args) throws Exception {
        KeyValuePair object = new KeyValuePair();
        object.setKey("G3-T02"); object.setValue("fragment-boundary");
        byte[] frame = LMCPFactory.packMessage(object, true);
        for (int boundary = 1; boundary < frame.length; boundary++) {
            final int split = boundary;
            InputStream chunks = new ByteArrayInputStream(frame) {
                @Override public synchronized int read(byte[] out, int at, int count) {
                    int available = pos < split ? split - pos : count;
                    return super.read(out, at, Math.min(count, available));
                }
            };
            KeyValuePair result = (KeyValuePair) SentinelMessageReader.read(chunks);
            require(result.getValue().equals(object.getValue()) && chunks.read() == -1);
        }
        byte[] pair = new byte[frame.length * 2];
        System.arraycopy(frame, 0, pair, 0, frame.length);
        System.arraycopy(frame, 0, pair, frame.length, frame.length);
        InputStream joined = new ByteArrayInputStream(pair);
        SentinelMessageReader.read(joined); SentinelMessageReader.read(joined);
        require(joined.read() == -1);
        for (int end = 0; end < frame.length; end++) {
            try {
                SentinelMessageReader.read(new ByteArrayInputStream(Arrays.copyOf(frame, end)));
                throw new AssertionError("Truncated stream accepted");
            } catch (IOException expected) { }
            // A new connection owns a new reader; no partial frame may carry over.
            SentinelMessageReader.read(new ByteArrayInputStream(frame));
        }
        int negative = 0;
        for (Path file : Files.newDirectoryStream(Path.of(args[0]), "*.bin")) {
            try {
                SentinelMessageReader.read(new ByteArrayInputStream(Files.readAllBytes(file)));
                throw new AssertionError("Malformed frame accepted: " + file);
            } catch (IOException expected) { negative++; }
        }
        require(negative >= 8);
        System.out.println("PASS split=" + (frame.length - 1) + " eof=" + frame.length
                + " coalesced=2 malformed=" + negative);
    }
}
