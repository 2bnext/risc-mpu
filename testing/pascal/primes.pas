program primes;

var i, j: integer;

begin
  for i := 3 to 999 do begin
    j := 2;
    while (j <= i) and (i mod j <> 0) do
      j := j + 1;
    if i = j then
      write(i, ' ')
  end;
  writeln
end.
