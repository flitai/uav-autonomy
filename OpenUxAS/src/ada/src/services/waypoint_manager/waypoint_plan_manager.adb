with Ada.Containers;             use Ada.Containers;
with AVTAS.LMCP.Types;           use AVTAS.LMCP.Types;
with UxAS.Comms.LMCP_Net_Client; use UxAS.Comms.LMCP_Net_Client;
with LMCP_Messages;              use LMCP_Messages;
with Ada.Text_IO;                use Ada.Text_IO;

package body Waypoint_Plan_Manager with SPARK_Mode is

   use all type Pos64_WP_Maps.Formal_Model.M.Map;
   use all type Pos64_Nat64_Maps.Formal_Model.M.Map;
   use Pos64_Vectors.Formal_Model.M;

   ---------------------------------
   -- Extract_MissionCommand_Maps --
   ---------------------------------

   procedure Extract_MissionCommand_Maps
     (WaypointList : WP_Seq;
      Id_To_Waypoint : in out Pos64_WP_Map;
      Id_To_Next_Id : in out Pos64_Nat64_Map)
   with
     Post =>
       Waypoints_Are_Subset (Id_To_Waypoint, WaypointList)
       and then Have_Same_Keys (Id_To_Waypoint, Id_To_Next_Id)
       and then Id_Keys_Match_Waypoint_Ids (Id_To_Next_Id, Id_To_Waypoint);

   procedure Extract_MissionCommand_Maps
     (WaypointList : WP_Seq;
      Id_To_Waypoint : in out Pos64_WP_Map;
      Id_To_Next_Id : in out Pos64_Nat64_Map)
   is
      WP : Waypoint;
   begin

      Clear (Id_To_Next_Id);
      Clear (Id_To_Waypoint);

      for I in WP_Sequences.First .. Last (WaypointList) loop
         WP := Get (WaypointList, I);
         if WP.Number > 0 and then WP.NextWaypoint >= 0 then
            if not Contains (Id_To_Waypoint, Pos64 (WP.Number)) then
               Insert (Id_To_Waypoint, Pos64 (WP.Number), WP);
               Insert (Id_To_Next_Id, Pos64 (WP.Number), Nat64 (WP.NextWaypoint));
            end if;
         end if;

         pragma Loop_Invariant
           (Integer (Length (Id_To_Next_Id)) <= I - WP_Sequences.First + 1);
         pragma Loop_Invariant
           (Integer (Length (Id_To_Waypoint)) <= I - WP_Sequences.First + 1);
         pragma Loop_Invariant
           (Waypoints_Are_Subset (Id_To_Waypoint, WaypointList));
         pragma Loop_Invariant
           (Have_Same_Keys (Id_To_Waypoint, Id_To_Next_Id));
         pragma Loop_Invariant
           (Id_Keys_Match_Waypoint_Ids (Id_To_Next_Id, Id_To_Waypoint));
         -- The following corresponds to Waypoints_Are_Full_Subset and proves
         -- with "prove line" but not with "prove subprogram"
--           pragma Loop_Invariant
--             (for all K in WP_Sequences.First .. I =>
--                (if Get (WaypointList, K).Number > 0
--                   and then Get (WaypointList, K).NextWaypoint >= 0
--                   and then
--                     (for all J in WP_Sequences.First .. K - 1 =>
--                        (Get (WaypointList, J).Number /= Get (WaypointList, K).Number
--                         or else Get (WaypointList, J).NextWaypoint < 0))
--                 then
--                   (Contains (Id_To_Waypoint, Get (WaypointList, K).Number) and then
--                    Element (Id_To_Waypoint, Get (WaypointList, K).Number) =
--                      Get (WaypointList, K))));
      end loop;

   end Extract_MissionCommand_Maps;

   --------------------
   -- Construct_Path --
   --------------------

   procedure Construct_Path
     (First_Id : Pos64;
      Id_To_Next_Id : Pos64_Nat64_Map;
      Path : in out Pos64_Vector;
      Next_Index : out Vector_Index;
      Cycle_Index : out Ext_Vector_Index)
   with
     Pre =>
       Is_Empty (Path)
       and then not Is_Empty (Id_To_Next_Id)
       and then Contains (Id_To_Next_Id, First_Id),
     Post =>
       not Is_Empty (Path)
       and then Next_Index <= Last_Index (Path)
       and then Next_Index = 1
       and then FirstWaypoint_Is_First_Or_Second_Element (First_Id, Path)
       and then (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id))
       and then Elements_Are_Unique (Path)
       and then Path_Elements_Are_Successors (Path, Id_To_Next_Id)
       and then Cycle_Index_Is_Valid (Cycle_Index, Id_To_Next_Id, Path);

   procedure Construct_Path
     (First_Id : Pos64;
      Id_To_Next_Id : Pos64_Nat64_Map;
      Path : in out Pos64_Vector;
      Next_Index : out Vector_Index;
      Cycle_Index : out Ext_Vector_Index)
   is
      use Pos64_Vectors.Formal_Model.M;
      use all type Pos64_Vectors.Formal_Model.M.Sequence;
   begin

      Next_Index := 1;
      Cycle_Index := 0;

      -- Append predecessor to First_Id to the list if found
      for Id of Id_To_Next_Id loop
         pragma Loop_Invariant (Is_Empty (Path));
         if not (Id = First_Id) and then
           Successor (Id_To_Next_Id, Id) = First_Id
         then
            Append (Path, Id);
            exit;
         end if;
      end loop;

      -- Append First_Id to the list
      Append (Path, First_Id);

      -- Append successors to the list, looking for cycle as we go
      while Length (Path) < Length (Id_To_Next_Id) loop
         if Path_Has_Cycle (Id_To_Next_Id, Path) then
            Cycle_Index :=
              Find_Index (Path,
                          Successor (Id_To_Next_Id, Last_Element (Path)));
            pragma Assert
              (Valid_Non_Zero_Cycle_Index (Cycle_Index, Path, Id_To_Next_Id));
            return;
         elsif Successor (Id_To_Next_Id, Last_Element (Path)) = 0
           or else not
             Contains
               (Id_To_Next_Id,
                Pos64 (Successor (Id_To_Next_Id, Last_Element (Path))))
           or else
             Contains
             (Path, Successor (Id_To_Next_Id, Last_Element (Path)))
         then
            return;
         else
            Append (Path, Successor (Id_To_Next_Id, Last_Element (Path)));
         end if;

         pragma Loop_Invariant (not Is_Empty (Path));
         pragma Loop_Invariant (Length (Model (Path)) >= 2);
         pragma Loop_Invariant
           (FirstWaypoint_Is_First_Or_Second_Element (First_Id, Path));
         pragma Loop_Invariant
           (for all Id of Model (Path) => Contains (Id_To_Next_Id, Id));
         pragma Loop_Invariant
           (Path_Elements_Are_Successors (Path, Id_To_Next_Id));
         pragma Loop_Invariant
           (Elements_Are_Unique (Path));
      end loop;

      if Path_Has_Cycle (Id_To_Next_Id, Path) then
         Cycle_Index :=
           Find_Index (Path, Successor (Id_To_Next_Id, Last_Element (Path)));
      end if;
   end Construct_Path;

   ---------------------------
   -- Handle_MissionCommand --
   ---------------------------

   procedure Handle_MissionCommand
     (State : in out Waypoint_Plan_Manager_State;
      MC : MissionCommand)
   is
      First_Id : constant Pos64 := MC.FirstWaypoint;
   begin

      -- Initialize relevant values of the state
      Clear (State.Id_To_Waypoint);
      State.MC := MC;
      State.New_Command := True;
      Clear (State.Path);
      State.Next_Index := 0;
      State.Cycle_Index := 0;
      State.Next_First_Id := 0;
      Extract_MissionCommand_Maps
        (State.MC.WaypointList, State.Id_To_Waypoint, State.Id_To_Next_Id);

      -- Check whether the first waypoint ID can be found in the map of valid
      -- waypoint IDs. If not, return.
      if not Contains (State.Id_To_Next_Id, First_Id) then
         return;
      end if;

      -- Otherwise, construct the path from which segments will be served
      Construct_Path (First_Id,
                      State.Id_To_Next_Id,
                      State.Path,
                      State.Next_Index,
                      State.Cycle_Index);

      State.Next_First_Id := First_Id;

   end Handle_MissionCommand;

   ------------------------
   -- Initialize_Segment --
   ------------------------

   procedure Lemma_Mod_Incr (A : Natural; B : Positive) with
     Ghost,
     Pre => A < Integer'Last,
     Post =>
       (if A mod B = B - 1 then (A + 1) mod B = 0
          else (A + 1) mod B = A mod B + 1);

   procedure Lemma_Mod_Incr (A : Natural; B : Positive) is null;

   procedure Initialize_Segment
     (Path : Pos64_Vector;
      Cycle_Index : Ext_Vector_Index;
      Current_Index : Vector_Index;
      Desired_Length : Positive;
      Overlap : Positive;
      Segment : in out Pos64_Vector;
      Next_Index : out Ext_Vector_Index;
      Next_First_Id : out Nat64)
   with
     Pre =>
       Is_Empty (Segment)
       and then Path_Is_Valid_Size_And_Indices_In_Range
                  (Path, Current_Index, Cycle_Index)
       and then Overlap in 2 .. Positive (Max) - 1
       and then Desired_Length in Overlap + 1 .. Positive (Max),
     Post =>
       Element (Segment, 1) = Element (Path, Current_Index)
       and then Is_Subsegment_Of_Path (Segment, Path, Current_Index, Cycle_Index)
       and then
       (if Cycle_Index > 0 then
          Positive (Length (Segment)) = Desired_Length
          and then Next_Index in 1 .. Last (Model (Path))
          and then Next_Segment_Will_Overlap_Current_Segment
                     (Path, Cycle_Index, Next_First_Id, Next_Index, Segment, Overlap)
        else
          (if Remaining_Path_Length (Path, Current_Index) > Desired_Length then
             Positive (Length (Segment)) = Desired_Length
             and then Next_Index = Current_Index + Desired_Length - Overlap
             and then Next_Segment_Will_Overlap_Current_Segment
                        (Path, Cycle_Index, Next_First_Id, Next_Index, Segment, Overlap)
           else
             Positive (Length (Segment)) = Remaining_Path_Length (Path, Current_Index)
             and then Next_Index = 0 and then Next_First_Id = 0));

   procedure Initialize_Segment
     (Path : Pos64_Vector;
      Cycle_Index : Ext_Vector_Index;
      Current_Index : Vector_Index;
      Desired_Length : Positive;
      Overlap : Positive;
      Segment : in out Pos64_Vector;
      Next_Index : out Ext_Vector_Index;
      Next_First_Id : out Nat64)
   is
      Len : Positive;
      Ind : Positive := Current_Index;
      Seg_Overlap_Ind : Positive;
      use Pos64_Vectors.Formal_Model;
      use Pos64_Vectors.Formal_Model.M;
   begin

      Next_Index := 0;

      if Cycle_Index > 0 then
         Len := Desired_Length;
         Seg_Overlap_Ind := Len - Overlap + 1;
         for I in 1 .. Len loop
            pragma Loop_Invariant
              (Ind =
                 (if Current_Index + I - 1 <= Last_Index (Path) then
                       Current_Index + I - 1
                  else
                    (Current_Index + I - 1 - Last_Index (Path) - 1) mod
                    (Last_Index (Path) - Cycle_Index + 1) + Cycle_Index));
            pragma Loop_Invariant
              (if I > Seg_Overlap_Ind then
                  Next_Index in 1 .. Last_Index (Path) and then
                  Element (Segment, Seg_Overlap_Ind) =
                    Element (Path, Next_Index));
            pragma Loop_Invariant
              (Is_Subsegment_Of_Path
                 (Segment, Path, Current_Index, Cycle_Index));
            pragma Loop_Invariant (Last_Index (Segment) = I - 1);

            Append (Segment, Element (Path, Ind));
            if Current_Index + I - 1 > Last_Index (Path) then
               Lemma_Mod_Incr (Current_Index + I - 1 - Last_Index (Path) - 1,
                               Last_Index (Path) - Cycle_Index + 1);
            end if;
            if I = Seg_Overlap_Ind then
               Next_Index := Ind;
               pragma Assert (Element (Segment, Seg_Overlap_Ind) =
                                Element (Path, Next_Index));
            end if;
            if Ind = Last_Index (Path) then
               Ind := Cycle_Index;
            else
               Ind := Ind + 1;
            end if;

         end loop;
         if Next_Index < Last_Index (Path) then
            Next_First_Id := Element (Path, Next_Index + 1);
         else
            Next_First_Id := Element (Path, Cycle_Index);
         end if;

      else
         Len := (if Integer (Length (Path)) - Current_Index + 1 >=
                   Desired_Length
                 then Desired_Length
                 else Integer (Length (Path)) - Current_Index + 1);
         for I in 1 .. Len loop
            Append (Segment, Element (Path, Ind));
            Ind := Ind + 1;
            pragma Loop_Invariant (Ind = Current_Index + I);
            pragma Loop_Invariant (Last_Index (Segment) = I);
            pragma Loop_Invariant (Element (Segment, 1) =
                                     Element (Path, Current_Index));
            pragma Loop_Invariant
              (for all J in 1 .. Last_Index (Segment) =>
                   Element (Segment, J) =
                   Element (Path, Current_Index + J - 1));
         end loop;

         if Remaining_Path_Length (Path, Current_Index) > Desired_Length then
            Next_Index := Current_Index + Desired_Length - Overlap;
            Next_First_Id := Element (Path, Next_Index + 1);
         else
            Next_Index := 0;
            Next_First_Id := 0;
         end if;

      end if;

   end Initialize_Segment;

   ---------------------
   -- Produce_Segment --
   ---------------------

   procedure Produce_Segment
     (State : in out Waypoint_Plan_Manager_State;
      Config : Waypoint_Plan_Manager_Configuration_Data;
      Mailbox : in out Waypoint_Plan_Manager_Mailbox)
   is
      New_Path_Index : Ext_Vector_Index;
      New_First_Id : Nat64;
   begin

      Clear (State.Segment);

      Initialize_Segment (State.Path,
                          State.Cycle_Index,
                          State.Next_Index,
                          Positive (Config.NumberWaypointsToServe),
                          Positive (Config.NumberWaypointsOverlap),
                          State.Segment,
                          New_Path_Index,
                          New_First_Id);

      declare
         MC_Out : MissionCommand := State.MC;
         WP_List : WP_Seq;
         Id : Pos64;
         WP : Waypoint;
         Last_WP : Waypoint with Ghost;
      begin
         MC_Out.FirstWaypoint := State.Next_First_Id;
         for I in First_Index (State.Segment) .. Last_Index (State.Segment) loop
            Id := Element (State.Segment, I);
            WP := Element (State.Id_To_Waypoint, Id);
            if I = Last_Index (State.Segment) then
               WP.NextWaypoint := WP.Number;
               Last_WP := WP;
               -- TODO: Extend SPARK messages to handle
               -- VehicleAction -> NavigationAction -> LoiterAction
               -- VehicleAction -> PayloadAction -> GimbalAngleAction
            end if;
            WP_List := Add (WP_List, WP);

            pragma Loop_Invariant (Length (WP_List) = To_Big_Integer (I));
            pragma Loop_Invariant
              (for all J in First_Index (State.Segment) .. I =>
                   (if J /= Last_Index (State.Segment) then
                           Get (WP_List, J) = Element (State.Id_To_Waypoint, Element (State.Segment, J))
                    else Get (WP_List, J) = Last_WP));
         end loop;

         pragma Assert
           (for all I in First_Index (State.Segment) .. Last_Index (State.Segment) =>
                (if I /= Last_Index (State.Segment) then
                        Get (WP_List, I) = Element (State.Id_To_Waypoint, Element (State.Segment, I))
                 else Get (WP_List, I) = Last_WP));
         MC_Out.WaypointList := WP_List;
         sendBroadcastMessage (Mailbox, MC_Out);
      end;

      State.Next_Index := New_Path_Index;
      State.Next_First_Id := New_First_Id;
      State.New_Command := False;

   end Produce_Segment;

end Waypoint_Plan_Manager;
