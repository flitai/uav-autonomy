with SPARK.Big_Integers;                         use SPARK.Big_Integers;
with SPARK.Containers.Formal.Hashed_Maps;
with SPARK.Containers.Formal.Vectors;

with Ada.Containers;                         use all type Ada.Containers.Count_Type;
with Waypoint_Plan_Manager_Mailboxes;        use Waypoint_Plan_Manager_Mailboxes;
with Common;                                 use Common;
with LMCP_Messages;                          use LMCP_Messages;

package Waypoint_Plan_Manager with SPARK_Mode is

   use Common.Count_Type_To_Big_Integer_Conversions;

   Max : constant Ada.Containers.Count_Type := 2000;

   subtype Pos64 is Int64 range 1 .. Int64'Last;
   subtype Nat64 is Int64 range 0 .. Int64'Last;

   subtype Ext_Vector_Index is Natural range 0 .. Integer (Max);
   subtype Vector_Index is Natural range 1 .. Integer (Max);

   function Pos64_Hash (X : Pos64) return Ada.Containers.Hash_Type is
     (Ada.Containers.Hash_Type'Mod (X));
   package Pos64_WP_Maps is new
     SPARK.Containers.Formal.Hashed_Maps (Pos64, Waypoint, Pos64_Hash);
   use Pos64_WP_Maps;
   subtype Pos64_WP_Map is
     Pos64_WP_Maps.Map (Max, Pos64_WP_Maps.Default_Modulus (Max))
       with Predicate => (for all Id of Pos64_WP_Map =>
                           (Element (Pos64_WP_Map, Id).Number = Id and
                            Element (Pos64_WP_Map, Id).NextWaypoint >= 0));

   package Pos64_Nat64_Maps is new
     SPARK.Containers.Formal.Hashed_Maps (Pos64, Nat64, Pos64_Hash);
   use Pos64_Nat64_Maps;
   subtype Pos64_Nat64_Map is
     Pos64_Nat64_Maps.Map (Max, Pos64_Nat64_Maps.Default_Modulus (Max));

   package Pos64_Vectors is new SPARK.Containers.Formal.Vectors (Positive, Pos64);
   subtype Pos64_Vector is Pos64_Vectors.Vector (Max);
   package Pos_Vec_M renames Pos64_Vectors.Formal_Model.M;
   use Pos64_Vectors;

   use Pos64_WP_Maps.Formal_Model;
   use Pos64_Nat64_Maps.Formal_Model;
   use Pos64_Vectors.Formal_Model;

   function Successor
     (M : Pos64_Nat64_Map; K : Pos64) return Nat64
      renames Element;

   function Successor
     (M : Pos64_Nat64_Maps.Formal_Model.M.Map; K : Pos64) return Nat64
      renames Pos64_Nat64_Maps.Formal_Model.Element;

   type Waypoint_Plan_Manager_Configuration_Data is record
      -- Number of waypoints remaining before starting the next segment.
      -- Value must be in [2, Max - 1]
      NumberWaypointsOverlap : Common.UInt32 := 2;
      -- Max number of waypoints to serve for each segment.
      -- Value must be in [NumberWaypointsOverlap + 1, Max].
      -- Default to Max to serve them all.
      NumberWaypointsToServe : Common.UInt32 := Common.UInt32 (Max);
      -- Radius to use for loiters added by the waypoint manager
      LoiterRadiusDefault : Common.Real64 := 200.0;
      -- Turn type to use for loiters added by the waypoint manager
      TurnType : LMCP_Messages.TurnTypeEnum := TurnShort;
      -- Gimbal payload ID to use for loiters added by the waypoint manager
      GimbalPayloadId : Common.Int64 := -1;
      -- Vehicle ID of managed vehicle
      VehicleID : Common.Int64 := -1;
   end record with
     Predicate =>
       (NumberWaypointsOverlap >= 2 and then
        NumberWaypointsOverlap <= UInt32 (Max) - 1 and then
        NumberWaypointsToServe > NumberWaypointsOverlap and then
        NumberWaypointsToServe <= UInt32 (Max));

   type Waypoint_Plan_Manager_State is record
      -- Copy of most recent MissionCommand
      MC : MissionCommand;
      -- Id -> copy of Waypoint message from MC
      Id_To_Waypoint : Pos64_WP_Map;
      -- Id -> successor waypoint Id in MC
      Id_To_Next_Id : Pos64_Nat64_Map;
      -- Ordered list of waypoint Ids, built using info in Id_To_Next_Id and
      -- based on MC.FirstWaypoint
      Path : Pos64_Vector;
      -- If MC.WaypointList has a cycle, this is the index in Path that forms a
      -- cycle with the the last element. Otherwise, it is 0.
      Cycle_Index : Ext_Vector_Index;
      -- Most recent segment
      Segment : Pos64_Vector;
      -- The waypoint Id to use for FirstWaypoint of the next segment
      Next_First_Id : Nat64;
      -- Index in Path for start of segment after this one
      Next_Index : Ext_Vector_Index;
      -- Whether the most recent MissionCommand has yet been used to produce a segment
      New_Command : Boolean;
      -- Whether vehicle is headed toward Next_First_Id
      Headed_To_First_Id : Boolean := False;
   end record;

   function Waypoints_Are_Subset
     (Id_To_Waypoint : Pos64_WP_Map;
      WaypointList : WP_Seq) return Boolean
   is
     (for all Id of Model (Id_To_Waypoint) =>
        Contains (WaypointList, WP_Sequences.First, Last (WaypointList),
                  Element (Id_To_Waypoint, Id)))
   with Ghost, Global => null;

   -- The following is the "platinum" version of Waypoints_Are_Subset.
   -- It is currently unused. It seems to be too complex for the provers to
   -- reason about in the full context of Extract_MissionCommand_Maps.
   function Waypoints_Are_Full_Subset
     (Id_To_Waypoint : Pos64_WP_Map;
      WaypointList : WP_Seq) return Boolean
   is
     (for all I in WP_Sequences.First .. Last (WaypointList) =>
          (if Get (WaypointList, I).Number > 0
              and then Get (WaypointList, I).NextWaypoint >= 0 and then
             (for all J in WP_Sequences.First .. I - 1 =>
                (Get (WaypointList, J).Number /= Get (WaypointList, I).Number
                 or else Get (WaypointList, J).NextWaypoint < 0))
           then
             (Contains (Id_To_Waypoint, Get (WaypointList, I).Number) and then
              Element (Id_To_Waypoint, Get (WaypointList, I).Number) =
                Get (WaypointList, I))))
   with Ghost, Global => null;

   function Have_Same_Keys
     (M : Pos64_WP_Map;
      N : Pos64_Nat64_Map) return Boolean
   is
     ((for all I of Model (M) => Contains (N, I))
       and then (for all I of Model (N) => Contains (M, I)))
   with Ghost, Global => null;

   function Elements_Are_Unique
     (V : Pos64_Vector) return Boolean
   is
     (for all I in Pos_Vec_M.First .. Pos_Vec_M.Last (Model (V)) =>
        (for all J in Pos_Vec_M.First .. Pos_Vec_M.Last (Model (V)) =>
             (if I /= J then
                   Element (V, I) /= Element (V, J))))
     with Ghost, Global => null;

   function Id_Keys_Match_Waypoint_Ids
     (Id_To_Next_Id : Pos64_Nat64_Map;
      Id_To_Waypoint : Pos64_WP_Map) return Boolean
   is
     (for all Id of Model (Id_To_Next_Id) =>
           Contains (Id_To_Waypoint, Id) and then
             Element (Id_To_Next_Id, Id) =
               Element (Id_To_Waypoint, Id).NextWaypoint)
   with Ghost, Global => null;

   function Path_Elements_Are_Successors
     (Path : Pos64_Vector;
      Id_To_Next_Id : Pos64_Nat64_Map) return Boolean
   is
     (for all I in First_Index (Path) .. Last_Index (Path) - 1 =>
           Successor (Id_To_Next_Id, Element (Path, I)) =
             Element (Path, I + 1))
   with
     Ghost,
     Pre =>
       (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id));

   function FirstWaypoint_Is_First_Or_Second_Element
     (FirstWaypoint : Pos64;
      Path : Pos64_Vector) return Boolean
   is
     (Element (Path, 1) = FirstWaypoint or else
          (Length (Path) > 1 and then Element (Path, 2) = FirstWaypoint))
   with
     Ghost,
     Pre => Length (Path) > 0;

   function Path_Has_Cycle
     (Id_To_Next_Id : Pos64_Nat64_Map;
      Path : Pos64_Vector) return Boolean
   is
     (Successor (Id_To_Next_Id, Last_Element (Path)) /= 0 and then
      Contains (Path, Successor (Id_To_Next_Id, Last_Element (Path))) and then
      Successor (Id_To_Next_Id, Last_Element (Path)) /= Last_Element (Path))
   with
     Pre =>
       Length (Path) > 0 and then
       (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id));

   function Valid_Non_Zero_Cycle_Index
     (Cycle_Index : Vector_Index;
      Path : Pos64_Vector;
      Id_To_Next_Id : Pos64_Nat64_Map) return Boolean
   is
     (Cycle_Index in 1 .. Last_Index (Path) - 1 and then
      Element (Path, Cycle_Index) =
        Successor (Id_To_Next_Id, Last_Element (Path)))
   with
     Ghost,
     Pre =>
       Length (Path) > 0 and then
       (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id));

   function Is_Subsegment_Of_Path
     (Segment : Pos64_Vector;
      Path : Pos64_Vector;
      Current_Index : Vector_Index;
      Cycle_Index : Ext_Vector_Index) return Boolean
   is
     (if Cycle_Index = 0 then
         Integer (Length (Segment)) <= Integer (Length (Path)) - Current_Index + 1 and then
        (for all I in 1 .. Last_Index (Segment) =>
           Element (Segment, I) = Element (Path, Current_Index + I - 1))
      else
        (for all I in 1 .. Last_Index (Segment) =>
          (if Current_Index + I - 1 <= Last_Index (Path) then
                Element (Segment, I) = Element (Path, Current_Index + I - 1)
           else
                Element (Segment, I) =
                  Element (Path, (Current_Index + I - 1 - Last_Index (Path) - 1) mod
                            (Last_Index (Path) - Cycle_Index + 1) + Cycle_Index))))
   with
     Ghost,
     Pre =>
     Last_Index (Path) <= Integer (Max)
     and Cycle_Index in 0 .. Last_Index (Path) - 1
     and Current_Index in 1 .. Last_Index (Path)
     and Last_Index (Segment) <= Integer (Max);

   function Remaining_Path_Length
     (Path : Pos64_Vector;
      Current_Index : Vector_Index) return Positive
   is
     (Positive (Length (Path)) - Current_Index + 1)
   with
     Pre =>
       Integer (Length (Path)) >= Current_Index;

   function Next_First_Id_Will_Be_Element_After_Next_Index
     (Next_First_Id : Pos64;
      Next_Index : Vector_Index;
      Cycle_Index : Ext_Vector_Index;
      Path : Pos64_Vector) return Boolean
   is
     (if Cycle_Index > 0 then
        (if Next_Index < Last_Index (Path) then
              Next_First_Id = Element (Path, Next_Index + 1)
         else
            Next_First_Id = Element (Path, Cycle_Index))
      else
         Next_First_Id = Element (Path, Next_Index + 1))
   with
     Ghost,
     Pre =>
       (if Cycle_Index > 0 then
          Cycle_Index in 1 .. Last_Index (Path) - 1 and then
          Next_Index in 1 .. Last_Index (Path)
        else
          Next_Index in 1 .. Last_Index (Path) - 1);

   function Next_Segment_Will_Overlap_Current_Segment
     (Path : Pos64_Vector;
      Cycle_Index : Ext_Vector_Index;
      Next_First_Id : Pos64;
      Next_Index : Vector_Index;
      Segment : Pos64_Vector;
      Overlap : Positive) return Boolean
   is
     (Element (Segment, Last_Index (Segment) - Overlap + 1) =
        Element (Path, Next_Index)
     and then
     (if Cycle_Index > 0 then
        (if Next_Index < Last_Index (Path) then
            Next_First_Id = Element (Path, Next_Index + 1)
         else
            Next_First_Id = Element (Path, Cycle_Index))
      else
         Next_First_Id = Element (Path, Next_Index + 1)))
   with
     Ghost, Global => null,
     Pre =>
       Integer (Length (Segment)) >= Overlap and then
       Next_Index in 1 .. Last_Index (Path) and then
       (if Cycle_Index > 0 then
           Cycle_Index in 1 .. Last_Index (Path) - 1 and then
           Next_Index in 1 .. Last_Index (Path)
        else
           Next_Index in 1 .. Last_Index (Path) - 1);

   function Path_Is_Valid_Size_And_Indices_In_Range
     (Path : Pos64_Vector;
      Next_Index : Ext_Vector_Index;
      Cycle_Index : Ext_Vector_Index) return Boolean
   is
      (Length (Path) > 0 and then
       Last_Index (Path) <= Positive (Max) and then
       Next_Index in 1 .. Last_Index (Path) and then
       Cycle_Index in 0 .. Last_Index (Path) - 1)
   with Ghost, Global => null;

   function Rest_Of_State_Unchanged
     (State_Old,
      State : Waypoint_Plan_Manager_State) return Boolean
   is
     (State_Old.MC = State.MC
      and then State_Old.Id_To_Waypoint = State.Id_To_Waypoint
      and then State_Old.Id_To_Next_Id = State.Id_To_Next_Id
      and then State_Old.Path = State.Path
      and then State_Old.Cycle_Index = State.Cycle_Index
      and then State_Old.Headed_To_First_Id = State.Headed_To_First_Id)
   with Ghost, Global => null;

   function Initial_Path_Parameters_Are_Valid
     (Path : Pos64_Vector;
      FirstWaypoint : Pos64;
      Next_Index : Ext_Vector_Index;
      Next_First_Id : Nat64) return Boolean
   is
     (Next_Index = 1 and then Next_First_Id = FirstWaypoint and then
      FirstWaypoint_Is_First_Or_Second_Element (FirstWaypoint, Path))
   with
     Ghost, Global => null,
     Pre => Length (Path) > 0;

   function Cycle_Index_Is_Valid
     (Cycle_Index : Ext_Vector_Index;
      Id_To_Next_Id : Pos64_Nat64_Map;
      Path : Pos64_Vector) return Boolean
   is
     (if Path_Has_Cycle (Id_To_Next_Id, Path) then
        (Cycle_Index in 1 .. Last_Index (Path) - 1 and then
         Element (Path, Cycle_Index) =
           Successor (Id_To_Next_Id, Last_Element (Path)))
      else
         Cycle_Index = 0)
   with
     Ghost, Global => null,
     Pre =>
       Length (Path) > 0 and then
       (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id));

   function Is_Valid_Path_Remaining
     (Path : Pos64_Vector;
      Next_Index : Ext_Vector_Index;
      Cycle_Index : Ext_Vector_Index;
      Next_First_Id : Nat64) return Boolean
   is
     (if Cycle_Index = 0 then
         Next_Index < Last_Index (Path) and then
         Element (Model (Path), Next_Index + 1) = Next_First_Id
      else
        (if Next_Index < Last_Index (Path) then
              Element (Model (Path), Next_Index + 1) = Next_First_Id
         else
            Cycle_Index in 1 .. Last_Index (Path) - 1 and then
            Element (Model (Path), Cycle_Index) = Next_First_Id))
   with Ghost, Global => null;

   procedure Handle_MissionCommand
     (State : in out Waypoint_Plan_Manager_State;
      MC : MissionCommand)
     with
       Pre => MC.FirstWaypoint > 0,
       Post =>
         State.MC = MC
         and then Waypoints_Are_Subset (State.Id_To_Waypoint, State.MC.WaypointList)
         and then Have_Same_Keys (State.Id_To_Waypoint, State.Id_To_Next_Id)
         and then Id_Keys_Match_Waypoint_Ids (State.Id_To_Next_Id, State.Id_To_Waypoint)
         and then (for all Id of Model (State.Path) => Contains (State.Id_To_Next_Id, Id))
         and then Elements_Are_Unique (State.Path)
         and then Path_Elements_Are_Successors (State.Path, State.Id_To_Next_Id)
         and then
         (if not Contains (Model (State.Id_To_Next_Id), MC.FirstWaypoint) then
            Is_Empty (State.Path) and State.Next_First_Id = 0 and
            State.Next_Index = 0 and State.Cycle_Index = 0
          else
            Length (State.Path) > 0
            and then Initial_Path_Parameters_Are_Valid
                      (State.Path, State.MC.FirstWaypoint, State.Next_Index, State.Next_First_Id)
            and then
            Cycle_Index_Is_Valid (State.Cycle_Index, State.Id_To_Next_Id, State.Path));

   procedure Produce_Segment
     (State : in out Waypoint_Plan_Manager_State;
      Config : Waypoint_Plan_Manager_Configuration_Data;
      Mailbox : in out Waypoint_Plan_Manager_Mailbox)
   with
     Pre =>
       State.MC.FirstWaypoint > 0
       and then Path_Is_Valid_Size_And_Indices_In_Range (State.Path, State.Next_Index, State.Cycle_Index)
       and then (for all Id of Model (State.Path) => Contains (State.Id_To_Waypoint, Id))
       and then Length (State.Path) > 0
       and then
       (if State.New_Command then
          Initial_Path_Parameters_Are_Valid (State.Path, State.MC.FirstWaypoint,
                                             State.Next_Index, State.Next_First_Id)
        else
          Is_Valid_Path_Remaining (State.Path, State.Next_Index,
                                   State.Cycle_Index, State.Next_First_Id)),
     Post =>
       State.New_Command = False
       and then Element (State.Segment, 1) = Element (State.Path, State'Old.Next_Index)
       and then Is_Subsegment_Of_Path (State.Segment, State.Path, State.Next_Index'Old, State.Cycle_Index)
       and then
       (if State.Cycle_Index > 0 then
          Positive (Length (State.Segment)) = Positive (Config.NumberWaypointsToServe)
          and then State.Next_Index in 1 .. Last_Index (State.Path)
          and then Next_Segment_Will_Overlap_Current_Segment
                     (State.Path, State.Cycle_Index, State.Next_First_Id, State.Next_Index,
                      State.Segment, Positive (Config.NumberWaypointsOverlap))
        else
          (if Remaining_Path_Length (State.Path, State.Next_Index'Old) >
                Positive (Config.NumberWaypointsToServe)
           then
             Positive (Length (State.Segment)) = Positive (Config.NumberWaypointsToServe)
             and then State.Next_Index = State.Next_Index'Old +
                        Positive (Config.NumberWaypointsToServe) -
                        Positive (Config.NumberWaypointsOverlap)
             and then Next_Segment_Will_Overlap_Current_Segment
                        (State.Path, State.Cycle_Index, State.Next_First_Id,
                         State.Next_Index, State.Segment,
                         Positive (Config.NumberWaypointsOverlap))
           else
             Positive (Length (State.Segment)) =
               Remaining_Path_Length (State.Path, State.Next_Index'Old)
           and then State.Next_Index = 0 and then State.Next_First_Id = 0))
       and then Rest_Of_State_Unchanged (State'Old, State);

private

end Waypoint_Plan_Manager;
