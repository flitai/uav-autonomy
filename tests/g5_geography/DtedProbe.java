import avtas.terrain.DTEDTile;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Locale;

/** Calls the unchanged formal AMASE reader. No simulation or GUI is started. */
public class DtedProbe {
    public static void main(String[] args) throws Exception {
        Locale.setDefault(Locale.ROOT);
        System.out.println("classSource\t" + DTEDTile.class.getProtectionDomain().getCodeSource().getLocation());
        HashMap<String, DTEDTile> tiles = new HashMap<>();
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String[] fields = line.split("\t");
            DTEDTile tile = tiles.computeIfAbsent(fields[0], key -> new DTEDTile(new File(key)));
            double lat = Double.parseDouble(fields[1]), lon = Double.parseDouble(fields[2]);
            System.out.printf("%s\t%.12f\t%.12f\t%d\t%.12f\t%.12f\t%.12f%n", fields[0], lat, lon,
                tile.getElevation(lat, lon), tile.getElevationInterp(lat, lon), tile.dlat, tile.dlon);
        }
    }
}
