with Common; use Common;

package Int64_Parsing with SPARK_Mode is

   procedure Parse_Int64 (S : String; V : out Int64) with
     Pre => S'Last < Integer'Last,
     Exceptional_Cases => (Parsing_Error => True);

   function Print_Int64 (V : Int64) return String;
end Int64_Parsing;
