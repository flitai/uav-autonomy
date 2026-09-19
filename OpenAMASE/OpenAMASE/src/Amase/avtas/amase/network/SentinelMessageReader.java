package avtas.amase.network;

import avtas.lmcp.LMCPFactory;
import avtas.lmcp.LMCPObject;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Strict, bounded Sentinel/attributes/LMCP input at the AMASE TCP boundary. */
public final class SentinelMessageReader {
    private static final int MAX_BODY = 1024 * 1024;
    private static final int MAX_ATTRIBUTES = 4096;

    private SentinelMessageReader() { }

    private static int next(InputStream input) throws IOException {
        int value = input.read();
        if (value < 0) {
            throw new EOFException("End of Sentinel stream");
        }
        return value;
    }

    private static void marker(InputStream input, String value, int start) throws IOException {
        for (int i = start; i < value.length(); i++) {
            if (next(input) != value.charAt(i)) {
                throw new IOException("Invalid Sentinel marker");
            }
        }
    }

    private static long decimal(InputStream input, String delimiter, int limit) throws IOException {
        long value = 0;
        int digits = 0;
        int b = next(input);
        while (b >= '0' && b <= '9') {
            if (++digits > limit) {
                throw new IOException("Oversized Sentinel decimal");
            }
            value = value * 10 + b - '0';
            b = next(input);
        }
        if (digits == 0 || b != delimiter.charAt(0)) {
            throw new IOException("Invalid Sentinel decimal");
        }
        marker(input, delimiter, 1);
        return value;
    }

    private static long checksum(byte[] bytes, int length) {
        long sum = 0;
        for (int i = 0; i < length; i++) {
            sum += bytes[i] & 0xff;
        }
        return sum & 0xffffffffL;
    }

    public static LMCPObject read(InputStream input) throws IOException {
        marker(input, "+=+=+=+=", 0);
        long size = decimal(input, "#@#@#@#@", 7);
        if (size < 27 || size > MAX_BODY) {
            throw new IOException("Sentinel body length outside limits");
        }
        byte[] body = new byte[(int) size];
        int offset = 0;
        while (offset < body.length) {
            int count = input.read(body, offset, body.length - offset);
            if (count < 0) {
                throw new EOFException("Truncated Sentinel body");
            }
            if (count == 0) {
                body[offset++] = (byte) next(input);
            } else {
                offset += count;
            }
        }
        marker(input, "!%!%!%!%", 0);
        if (decimal(input, "?^?^?^?^", 10) != checksum(body, body.length)) {
            throw new IOException("Sentinel checksum mismatch");
        }
        int first = -1;
        int second = -1;
        for (int i = 0; i < Math.min(body.length, MAX_ATTRIBUTES + 1); i++) {
            if ((body[i] & 0xff) > 127) {
                throw new IOException("Non-ASCII message attributes");
            }
            if (body[i] == '$') {
                if (first < 0) {
                    first = i;
                } else {
                    second = i;
                    break;
                }
            }
        }
        if (first <= 0 || second <= first) {
            throw new IOException("Missing or oversized message attributes");
        }
        String[] fields = new String(body, first + 1, second - first - 1,
                StandardCharsets.US_ASCII).split("\\|", -1);
        if (fields.length != 5 || !fields[0].equals("lmcp")
                || !fields[3].matches("[0-9]+") || !fields[4].matches("[0-9]+")) {
            throw new IOException("Invalid LMCP attributes");
        }
        byte[] raw = Arrays.copyOfRange(body, second + 1, body.length);
        if (raw.length < 27) {
            throw new IOException("Short LMCP message");
        }
        ByteBuffer header = ByteBuffer.wrap(raw);
        int contentSize = header.getInt(4);
        if (header.getInt(0) != LMCPFactory.LMCP_CONTROL_STR || contentSize < 15
                || contentSize != raw.length - 12 || raw[8] != 1) {
            throw new IOException("Invalid LMCP header or length");
        }
        if (Integer.toUnsignedLong(header.getInt(raw.length - 4)) != checksum(raw, raw.length - 4)) {
            throw new IOException("LMCP checksum mismatch");
        }
        try {
            LMCPObject object = LMCPFactory.getObject(raw);
            if (object == null || object.calcSize() != contentSize
                    || !object.getFullLMCPTypeName().equals(fields[1])) {
                throw new IOException("LMCP decoded size or descriptor mismatch");
            }
            return object;
        } catch (Exception ex) {
            throw new IOException("Cannot decode LMCP message", ex);
        }
    }
}
