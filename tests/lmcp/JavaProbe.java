import afrl.cmasi.AirVehicleState;
import afrl.cmasi.AltitudeType;
import afrl.cmasi.Location3D;
import avtas.lmcp.LMCPEnum;
import avtas.lmcp.LMCPFactory;
import avtas.lmcp.LMCPObject;
import uxas.messages.task.TaskActive;
import java.io.*;
import java.lang.reflect.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** File-only integration probe. No sockets, simulation or third-party dependencies. */
public final class JavaProbe {
    static void require(boolean value, String message) {
        if (!value) throw new IllegalStateException(message);
    }

    static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof String) return "\"" + ((String)value).replace("\\", "\\\\")
            .replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
        if (value instanceof Map) {
            List<String> parts = new ArrayList<>();
            for (Object key : ((Map<?,?>)value).keySet()) parts.add(json(key.toString()) + ":" + json(((Map<?,?>)value).get(key)));
            return "{" + String.join(",", parts) + "}";
        }
        if (value instanceof Iterable) {
            List<String> parts = new ArrayList<>();
            for (Object element : (Iterable<?>)value) parts.add(json(element));
            return "[" + String.join(",", parts) + "]";
        }
        return value.toString();
    }

    static void writeJson(Path path, Object value) throws Exception {
        Files.write(path, (json(value) + "\n").getBytes(StandardCharsets.UTF_8));
    }

    static Map<String,Object> inventory(Path namesFile) throws Exception {
        Map<String,Object> result = new TreeMap<>();
        for (String name : Files.readAllLines(namesFile, StandardCharsets.UTF_8)) {
            Class<?> type = Class.forName(name);
            Map<String,Object> entry = new TreeMap<>();
            TreeSet<String> api = new TreeSet<>();
            for (Method method : type.getMethods()) if (!method.isSynthetic() && !method.isBridge()) api.add(method.toGenericString());
            for (Constructor<?> ctor : type.getConstructors()) api.add(ctor.toGenericString());
            for (Field field : type.getFields()) api.add(field.toGenericString());
            entry.put("api", api);
            entry.put("loadedFrom", type.getProtectionDomain().getCodeSource().getLocation().toString());
            if (LMCPObject.class.isAssignableFrom(type) && !Modifier.isAbstract(type.getModifiers())) {
                LMCPObject object = (LMCPObject)type.getConstructor().newInstance();
                LMCPObject created = LMCPFactory.createObject(object.getLMCPSeriesNameAsLong(),object.getLMCPType(),object.getLMCPSeriesVersion());
                require(created != null && created.getClass().equals(type), "Factory cannot instantiate " + name);
                entry.put("kind", "struct");
                entry.put("typeId", object.getLMCPType());
                entry.put("series", object.getLMCPSeriesName());
                entry.put("seriesId", Long.toString(object.getLMCPSeriesNameAsLong()));
                entry.put("version", object.getLMCPSeriesVersion());
            } else if (type.isEnum()) {
                entry.put("kind", "enum");
                List<String> constants = new ArrayList<>();
                for (Object constant : type.getEnumConstants()) constants.add(constant.toString());
                entry.put("constants", constants);
            } else if (LMCPEnum.class.isAssignableFrom(type) && !type.isInterface()) {
                LMCPEnum series = (LMCPEnum)type.getConstructor().newInstance();
                entry.put("kind", "series");
                entry.put("series", series.getSeriesName());
                entry.put("seriesId", Long.toString(series.getSeriesNameAsLong()));
                entry.put("version", series.getSeriesVersion());
            } else entry.put("kind", "runtime");
            result.put(name, entry);
        }
        return result;
    }

    static Map<String,LMCPObject> objects(Path fixture) throws Exception {
        Properties p = new Properties();
        try (Reader reader = Files.newBufferedReader(fixture, StandardCharsets.UTF_8)) { p.load(reader); }
        Map<String,LMCPObject> result = new LinkedHashMap<>();
        for (String label : Arrays.asList("basic", "wide")) {
            AirVehicleState state = new AirVehicleState();
            state.setID(Long.parseLong(p.getProperty(label + ".id")));
            state.setTime(Long.parseLong(p.getProperty("time")));
            state.setHeading(Float.parseFloat(p.getProperty("heading")));
            state.setAirspeed(Float.parseFloat(p.getProperty("airspeed")));
            Location3D location = new Location3D();
            location.setLatitude(Double.parseDouble(p.getProperty("latitude")));
            location.setLongitude(Double.parseDouble(p.getProperty("longitude")));
            location.setAltitude(Float.parseFloat(p.getProperty("altitude")));
            location.setAltitudeType(AltitudeType.MSL);
            state.setLocation(location);
            if (label.equals("wide")) for (String id : p.getProperty("wide.tasks").split(",")) state.getAssociatedTasks().add(Long.parseLong(id));
            result.put(label, state);
        }
        TaskActive task = new TaskActive();
        task.setTaskID(Long.parseLong(p.getProperty("task.id")));
        task.setEntityID(Long.parseLong(p.getProperty("task.entity")));
        task.setTimeTaskActivated(Long.parseLong(p.getProperty("task.time")));
        result.put("task", task);
        return result;
    }

    static Map<String,Object> describe(LMCPObject object) {
        Map<String,Object> result = new TreeMap<>();
        result.put("type", object.getFullLMCPTypeName());
        result.put("version", object.getLMCPSeriesVersion());
        if (object instanceof AirVehicleState) {
            AirVehicleState s = (AirVehicleState)object;
            result.put("ID", Long.toString(s.getID())); result.put("Time", Long.toString(s.getTime()));
            result.put("Latitude", s.getLocation().getLatitude()); result.put("Longitude", s.getLocation().getLongitude());
            result.put("Altitude", s.getLocation().getAltitude()); result.put("AltitudeType", s.getLocation().getAltitudeType().toString());
            result.put("Heading", s.getHeading()); result.put("Airspeed", s.getAirspeed());
            List<String> tasks = new ArrayList<>();
            for (Long id : s.getAssociatedTasks()) tasks.add(id.toString());
            result.put("AssociatedTasks", tasks);
        } else {
            TaskActive s = (TaskActive)object;
            result.put("TaskID", Long.toString(s.getTaskID())); result.put("EntityID", Long.toString(s.getEntityID()));
            result.put("TimeTaskActivated", Long.toString(s.getTimeTaskActivated()));
        }
        return result;
    }

    static byte[] raw(LMCPObject object, boolean checksum) throws Exception {
        byte[] bytes = LMCPFactory.packMessage(object, checksum);
        if (checksum) {
            require(new String(bytes,0,8,StandardCharsets.US_ASCII).equals("+=+=+=+="), "Missing Sentinel prefix");
            bytes = LMCPFactory.getMessageBytes(new ByteArrayInputStream(bytes));
        }
        require(ByteBuffer.wrap(bytes).getInt() == 0x4c4d4350, "Wrong LMCP marker");
        require(LMCPFactory.getSize(bytes) + 12 == bytes.length, "Wrong frame length");
        require(LMCPFactory.validate(bytes), "Bad frame checksum");
        return bytes;
    }

    public static void main(String[] args) throws Exception {
        if (args[0].equals("inventory")) {
            writeJson(Paths.get(args[2]), inventory(Paths.get(args[1])));
            System.out.println("INVENTORY_OK"); return;
        }
        if (args[0].equals("unsupported")) {
            byte[] bytes = Files.readAllBytes(Paths.get(args[1]));
            ByteBuffer b = ByteBuffer.wrap(bytes);
            require(LMCPFactory.createObject(b.getLong(9), b.getInt(17) & 0xffffffffL, b.getShort(21) & 0xffff) == null,
                "Expected incompatible series version to be rejected");
            System.out.println("VERSION_REJECTED"); return;
        }
        if (args[0].equals("reject-corrupt")) {
            byte[] bytes = Files.readAllBytes(Paths.get(args[1]));
            require(!LMCPFactory.validate(bytes), "Corrupt sample passed checksum");
            boolean rejected = false;
            try { LMCPFactory.getObject(bytes); } catch (Exception expected) { rejected = true; }
            require(rejected, "Corrupt sample was decoded");
            System.out.println("CORRUPT_REJECTED"); return;
        }
        Map<String,LMCPObject> samples = objects(Paths.get(args[1]));
        Path directory = Paths.get(args[2]);
        Files.createDirectories(directory);
        Map<String,Object> report = new TreeMap<>();
        for (Map.Entry<String,LMCPObject> sample : samples.entrySet()) {
            String label = sample.getKey(); LMCPObject expected = sample.getValue();
            if (args[0].equals("verify-cmasi") && label.equals("task")) continue;
            for (boolean checksum : new boolean[]{false,true}) {
                String file = label + (checksum ? "-checksum.bin" : "-zero.bin");
                byte[] expectedBytes = raw(expected, checksum);
                if (args[0].equals("emit")) Files.write(directory.resolve(file), expectedBytes);
                else {
                    byte[] received = Files.readAllBytes(directory.resolve(file));
                    require(Arrays.equals(expectedBytes, received), "Re-encoded frame differs: " + file);
                    LMCPObject decoded = LMCPFactory.getObject(received);
                    require(decoded != null && describe(expected).equals(describe(decoded)), "Fields differ: " + file);
                }
            }
            if (args[0].equals("emit")) Files.write(directory.resolve(label + "-sentinel.bin"), LMCPFactory.packMessage(expected,true));
            report.put(label, describe(expected));
        }
        writeJson(Paths.get(args[3]), report);
        System.out.println("SAMPLES_OK " + args[0]);
    }
}
