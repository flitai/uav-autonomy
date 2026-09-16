# Spark Gold Waypoint Plan Manager Mission Command Example

This example is intended to test and demonstrate a SPARK/Ada implementation of the Waypoint Plan Manager (WPM) verified to the gold level. The WPM is configured to serve segments containing up to 15 waypoints, with an overlap of 5 waypoints between segments. The primary message used to drive this example is a mission command message for UAV 400 that contains:
* A waypoint at the location of UAV 500 with an ID number that duplicates that of an earlier waypoint in the waypoint list. This waypoint should therefore be ignored.
* Two valid waypoints that are given out of order with respect to the `Next` and `NextNumber` fields of waypoints in the waypoint list.
* A waypoint that causes a cycle back to an earlier waypoint.
* An extraneous waypoint at the location of UAV 500 that is not referenced by the `NextNumber` of any waypoints in the waypoint list. This waypoint should therefore be ignored.
See comments in the `MissionCommand_V400.xml` message that identify these waypoints.


## Files:
* `cfg_ada.xml` - The configuration file for the SPARK/Ada portions of OpenUxAS
* `cfg_cpp.xml` - The configuration file for the C++ portions of OpenUxAS
* `config.yaml` - The configuration file for script `run-examples`
* `Scenario_SparkGoldWPM.xml` - The AMASE scenario file
* `MessagesToSend/AirVehicle{Configuration,State}_V{400,500}.xml` - Air vehicle configuration and state messages for UAVs 400 and 500
* `MessagesToSend/MissionCommand_V400.xml` - The mission command message used to drive the example


## Running the Example:
1. Open a terminal window in main OpenUxAS directory
2. Enter the command: `./run-example 04_Ada_SparkGoldWPM`
3. Start the Amase simulation (i.e. push the play button)


### What Happens?
* When the Amase simulation starts, two UAVs will be initialized and begin loitering about two different locations.
* The UAV with ID 400 should soon start to follow a segment with 15 waypoints.
* Once the UAV reaches the last 5 waypoints of the segment, it should start following a new segment of 15 waypoints that overlaps the end of the previous segment.
* The third segment should result in a cycle back to an earlier waypoint.
* Note: UAV 400 should never go to the location of UAV 500.
