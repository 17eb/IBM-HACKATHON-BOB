      ******************************************************************
      * LOANCALC - monthly loan-servicing batch (synthetic sample).
      * Reads fixed-width loan records, computes monthly interest and
      * late fee, writes one detail record per input plus a trailer.
      * Layouts: docs/record_layouts.md.  Rules: R1-R5.
      * Usage:   loancalc <input-path> <output-path>
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOANCALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOAN-IN  ASSIGN TO WS-IN-PATH
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.
           SELECT LOAN-OUT ASSIGN TO WS-OUT-PATH
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-OUT-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  LOAN-IN.
       01  IN-REC.
           05  IN-CUST-ID          PIC X(8).
           05  IN-PRINCIPAL        PIC 9(7)V99.
           05  IN-RATE             PIC 9V9(4).
           05  IN-TERM             PIC 9(3).
           05  IN-DAYS-LATE        PIC 9(3).

       FD  LOAN-OUT.
       01  OUT-REC                 PIC X(37).

       WORKING-STORAGE SECTION.
       01  WS-IN-PATH              PIC X(256).
       01  WS-OUT-PATH             PIC X(256).
       01  WS-IN-STATUS            PIC XX.
       01  WS-OUT-STATUS           PIC XX.
       01  WS-EOF-FLAG             PIC X VALUE 'N'.
           88  END-OF-INPUT        VALUE 'Y'.
       01  WS-VALID-FLAG           PIC X VALUE 'Y'.
           88  REC-VALID           VALUE 'Y'.

       01  WS-INT                  PIC 9(7)V99.
       01  WS-FEE                  PIC 9(6)V99.
       01  WS-DUE                  PIC 9(7)V99.

       01  WS-REC-COUNT            PIC 9(6)     VALUE 0.
       01  WS-ERR-COUNT            PIC 9(6)     VALUE 0.
       01  WS-DUE-SUM              PIC 9(11)V99 VALUE 0.

       01  DETAIL-LINE.
           05  DL-CUST-ID          PIC X(8).
           05  DL-STATUS           PIC X(3).
           05  DL-INT              PIC 9(7)V99.
           05  DL-FEE              PIC 9(6)V99.
           05  DL-DUE              PIC 9(7)V99.

       01  TRAILER-LINE.
           05  TL-ID               PIC X(3) VALUE 'TRL'.
           05  TL-REC-COUNT        PIC 9(6).
           05  TL-ERR-COUNT        PIC 9(6).
           05  TL-DUE-SUM          PIC 9(11)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-IN-PATH  FROM ARGUMENT-VALUE
           ACCEPT WS-OUT-PATH FROM ARGUMENT-VALUE
           OPEN INPUT LOAN-IN
           IF WS-IN-STATUS NOT = '00'
               DISPLAY 'LOANCALC: cannot open input, status '
                   WS-IN-STATUS UPON SYSERR
               MOVE 12 TO RETURN-CODE
               STOP RUN
           END-IF
           OPEN OUTPUT LOAN-OUT
           IF WS-OUT-STATUS NOT = '00'
               DISPLAY 'LOANCALC: cannot open output, status '
                   WS-OUT-STATUS UPON SYSERR
               CLOSE LOAN-IN
               MOVE 12 TO RETURN-CODE
               STOP RUN
           END-IF
           PERFORM READ-INPUT
           PERFORM PROCESS-RECORD UNTIL END-OF-INPUT
           PERFORM WRITE-TRAILER
           CLOSE LOAN-IN LOAN-OUT
           STOP RUN.

       READ-INPUT.
           READ LOAN-IN
               AT END SET END-OF-INPUT TO TRUE
           END-READ.

       PROCESS-RECORD.
           ADD 1 TO WS-REC-COUNT
           PERFORM VALIDATE-RECORD
           IF REC-VALID
               PERFORM CALC-INTEREST
               PERFORM CALC-LATE-FEE
               COMPUTE WS-DUE = WS-INT + WS-FEE
               ADD WS-DUE TO WS-DUE-SUM
               MOVE 'OK ' TO DL-STATUS
           ELSE
               MOVE 0 TO WS-INT WS-FEE WS-DUE
               ADD 1 TO WS-ERR-COUNT
               MOVE 'ERR' TO DL-STATUS
           END-IF
           MOVE IN-CUST-ID TO DL-CUST-ID
           MOVE WS-INT     TO DL-INT
           MOVE WS-FEE     TO DL-FEE
           MOVE WS-DUE     TO DL-DUE
           WRITE OUT-REC FROM DETAIL-LINE
           PERFORM READ-INPUT.

      * R4: non-numeric fields, zero principal or zero rate -> ERR.
       VALIDATE-RECORD.
           MOVE 'Y' TO WS-VALID-FLAG
           IF IN-PRINCIPAL NOT NUMERIC
              OR IN-RATE NOT NUMERIC
              OR IN-TERM NOT NUMERIC
              OR IN-DAYS-LATE NOT NUMERIC
               MOVE 'N' TO WS-VALID-FLAG
           ELSE
               IF IN-PRINCIPAL = 0 OR IN-RATE = 0
                   MOVE 'N' TO WS-VALID-FLAG
               END-IF
           END-IF.

      * R1: monthly interest, rounded to cents.
       CALC-INTEREST.
           COMPUTE WS-INT ROUNDED = IN-PRINCIPAL * IN-RATE / 12.

      * R2: 5% of interest, truncated (no ROUNDED), minimum 5.00.
      * R3: over 60 days late, double the fee after the minimum.
       CALC-LATE-FEE.
           MOVE 0 TO WS-FEE
           IF IN-DAYS-LATE > 15
               COMPUTE WS-FEE = WS-INT * 0.05
               IF WS-FEE < 5.00
                   MOVE 5.00 TO WS-FEE
               END-IF
               IF IN-DAYS-LATE > 60
                   COMPUTE WS-FEE = WS-FEE * 2
               END-IF
           END-IF.

      * R5: trailer counts all records and errors; sums OK records.
       WRITE-TRAILER.
           MOVE WS-REC-COUNT TO TL-REC-COUNT
           MOVE WS-ERR-COUNT TO TL-ERR-COUNT
           MOVE WS-DUE-SUM   TO TL-DUE-SUM
           WRITE OUT-REC FROM TRAILER-LINE.
